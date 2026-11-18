import {
  CANVAS_SDK_MODULE_SOURCE,
  CANVAS_SDK_SPECIFIER,
} from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import builderSource from "../../../../../../../canvas/packages/canvas_builder/build.mjs?raw";
import {
  buildSandboxDocument,
  decodeJsxUnicodeEscapes,
  isInteractiveCanvasCommentTarget,
  resolveExternalAnchorUrl,
} from "./sandboxRuntime";

function clickTarget(html: string, selector: string): Element {
  const container = document.createElement("div");
  container.innerHTML = html;
  const element = container.querySelector(selector);
  if (!element) throw new Error(`selector ${selector} not found`);
  return element;
}

// Runs the document's import-map setup script against stub Blob/URL/document
// globals and returns the map it installs. jsdom has no createObjectURL, and
// asserting the map it produces beats matching the script's source text.
function installedImportMap(html: string): Record<string, string> {
  const setup = [
    ...new DOMParser()
      .parseFromString(html, "text/html")
      .querySelectorAll("script"),
  ].find((script) => script.textContent?.includes("canvasImportMap"));
  if (!setup?.textContent) throw new Error("import-map setup script not found");

  const blobs: string[] = [];
  const installed: { type?: string; textContent?: string } = {};
  const documentStub = {
    createElement: () => installed,
    head: { appendChild: () => undefined },
  };
  const urlStub = {
    createObjectURL: (blob: { parts: string[] }) =>
      `blob:${blobs.push(blob.parts.join("")) - 1}`,
  };
  class BlobStub {
    constructor(public parts: string[]) {}
  }

  new Function("document", "URL", "Blob", setup.textContent)(
    documentStub,
    urlStub,
    BlobStub,
  );

  expect(installed.type).toBe("importmap");
  const imports = JSON.parse(installed.textContent ?? "{}").imports;
  // Resolve blob handles back to their source so callers can assert content.
  for (const [name, url] of Object.entries(imports)) {
    const index = /^blob:(\d+)$/.exec(String(url))?.[1];
    if (index) imports[name] = blobs[Number(index)];
  }
  return imports;
}

describe("decodeJsxUnicodeEscapes", () => {
  it.each([
    {
      name: "decodes 4-hex escapes",
      input: "Survey started Jun 20, 2026 \\u00b7 live \\u00b7 data",
      expected: "Survey started Jun 20, 2026 · live · data",
    },
    { name: "decodes braced code points", input: "\\u{1F600}", expected: "😀" },
    {
      name: "decodes surrogate pairs",
      input: "\\ud83d\\ude00",
      expected: "😀",
    },
    {
      name: "decodes braced escapes shorter than 4 digits",
      input: "\\u{b7}",
      expected: "·",
    },
    {
      name: "leaves out-of-range code points intact",
      input: "\\u{110000}",
      expected: "\\u{110000}",
    },
    {
      name: "leaves incomplete escapes intact",
      input: "\\u00 and \\uZZZZ",
      expected: "\\u00 and \\uZZZZ",
    },
    {
      name: "leaves already-decoded text untouched",
      input: "plain · text",
      expected: "plain · text",
    },
    {
      name: "decodes valid escapes next to invalid ones",
      input: "\\u00b7 then \\u{110000}",
      expected: "· then \\u{110000}",
    },
  ])("$name", ({ input, expected }) => {
    expect(decodeJsxUnicodeEscapes(input)).toBe(expected);
  });
});

interface PostedMessage {
  type: string;
  id: string;
  method?: string;
  [key: string]: unknown;
}

interface PublishedRuntimeApi {
  navigate: {
    toNewTask: (options: { prompt: string; repository: string }) => void;
  };
  openExternal: (url: string) => void;
  state: { get: (key: string) => Promise<unknown> };
}

// Boots the published runtime (a string bundle) against stub globals and
// connects a fake host port, so a test can drive `ph.*` and answer the
// protocol messages it posts.
function bootPublishedRuntime(): {
  ph: PublishedRuntimeApi;
  userActivation: { isActive: boolean };
  posted: PostedMessage[];
  requests: () => PostedMessage[];
  respond: (id: string, body: Record<string, unknown>) => void;
} {
  const source = builderSource.match(/const runtime = `([^`]*)`/)?.[1];
  if (!source) throw new Error("Published runtime not found");
  const listeners = new Map<string, (event: unknown) => void>();
  const portListeners = new Map<string, (event: unknown) => void>();
  const posted: PostedMessage[] = [];
  const port = {
    postMessage: (message: PostedMessage) => posted.push(message),
    addEventListener: (name: string, listener: (event: unknown) => void) =>
      portListeners.set(name, listener),
    start: vi.fn(),
  };
  const frame = { ph: undefined as unknown as PublishedRuntimeApi };
  const userActivation = { isActive: true };
  const parent = {};
  new Function(
    "window",
    "document",
    "location",
    "parent",
    "navigator",
    "addEventListener",
    source,
  )(
    frame,
    document,
    { hash: "" },
    parent,
    { userActivation },
    (name: string, listener: (event: unknown) => void) =>
      listeners.set(name, listener),
  );
  listeners.get("message")?.({
    source: parent,
    data: { channel: "posthog-canvas", type: "connect" },
    ports: [port],
  });
  return {
    ph: frame.ph,
    userActivation,
    posted,
    requests: () => posted.filter((message) => message.type === "data-request"),
    respond: (id, body) =>
      portListeners.get("message")?.({
        data: { channel: "posthog-canvas", type: "data-response", id, ...body },
      }),
  };
}

describe("buildSandboxDocument", () => {
  it("publishes navigation and the same GitHub URL restriction as the host", () => {
    const { ph, userActivation, posted } = bootPublishedRuntime();

    ph.navigate.toNewTask({
      prompt: "Inspect this PR",
      repository: "example/app",
    });
    expect(posted.at(-1)).toEqual({
      channel: "posthog-canvas",
      type: "navigate",
      nav: {
        target: "compose-task",
        prompt: "Inspect this PR",
        repository: "example/app",
      },
    });
    ph.openExternal("https://github.com/example/app/pull/42");
    expect(posted.at(-1)).toEqual({
      channel: "posthog-canvas",
      type: "open-external",
      url: "https://github.com/example/app/pull/42",
    });
    expect(() => ph.openExternal("https://github.com/login")).toThrow(
      "not allowed",
    );
    expect(() =>
      ph.openExternal("https://github.com.evil.com/example/app/pull/42"),
    ).toThrow("not allowed");
    userActivation.isActive = false;
    expect(() =>
      ph.navigate.toNewTask({ prompt: "Inspect", repository: "example/app" }),
    ).toThrow("user action");
  });

  // A canvas that fans out more requests than the host runs at once gets its
  // extras refused once the host queue is full. Before the retry the cards
  // stayed broken until someone refreshed the whole canvas.
  it("sends a refused request again when the host marks it retryable", async () => {
    vi.useFakeTimers();
    try {
      const { ph, requests, respond } = bootPublishedRuntime();
      const read = ph.state.get("board");

      respond(requests()[0].id, {
        ok: false,
        error: "Too many canvas data requests are already waiting",
        retryable: true,
      });
      await vi.advanceTimersByTimeAsync(2_000);

      expect(requests()).toHaveLength(2);
      const retry = requests()[1];
      expect(retry.method).toBe("stateGet");
      respond(retry.id, { ok: true, result: { columns: 3 } });
      await expect(read).resolves.toEqual({ columns: 3 });
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives up on a refusal the host does not mark retryable", async () => {
    const { ph, requests, respond } = bootPublishedRuntime();
    const read = ph.state.get("board");

    respond(requests()[0].id, {
      ok: false,
      error: "Canvas data request is over the 64KB payload limit",
    });

    await expect(read).rejects.toThrow("64KB payload limit");
    expect(requests()).toHaveLength(1);
  });

  it("sends a refused request again in the authoring sandbox too", () => {
    const html = buildSandboxDocument();
    expect(html).toContain("d.retryable === true");
    expect(html).toContain("call(method, payload, attempt + 1)");
  });

  it("inlines the unicode-escape decoder into the bootstrap", () => {
    const html = buildSandboxDocument();
    expect(html).toContain(
      "const decodeUnicodeEscapes = function decodeJsxUnicodeEscapes(",
    );
    expect(html).toContain("jsxUnicodeEscapesPlugin");
  });

  // The SDK has no CDN pin, so it resolves only if the document mints it as a
  // blob module and registers it. Assembling the map at runtime also has to
  // keep the CDN pins it replaced, because losing those breaks every canvas
  // rather than only the ones importing the SDK.
  it("registers the canvas SDK alongside the CDN pins in the import map", () => {
    const imports = installedImportMap(buildSandboxDocument());

    expect(imports[CANVAS_SDK_SPECIFIER]).toBe(CANVAS_SDK_MODULE_SOURCE);
    expect(imports.react).toContain("esm.sh");
    expect(imports["react/jsx-runtime"]).toContain("esm.sh");
  });

  it("treats null connector options as an omitted refresh value", () => {
    expect(buildSandboxDocument()).toContain("refresh: options?.refresh");
  });

  it("inlines the external-anchor resolver into the bootstrap", () => {
    const html = buildSandboxDocument();
    expect(html).toContain(
      "const resolveExternalAnchorUrl = function resolveExternalAnchorUrl(",
    );
    expect(html).toContain('"open-external"');
    expect(html).toContain("event.defaultPrevented");
  });

  // The document paints before its stylesheets load and before the host's
  // theme message arrives. A light fallback there flashed white over a dark
  // app every time a canvas preview scrolled into view.
  it("paints nothing of its own before the host theme lands", () => {
    const html = buildSandboxDocument();
    expect(html).toContain("background: var(--background, transparent)");
    expect(html).not.toContain("var(--background, #fff)");
    expect(html).toContain("html.dark { color-scheme: dark; }");
  });

  it("installs the persisted comment protocol", () => {
    const html = buildSandboxDocument();
    expect(html).toContain('d.type === "set-comment-highlights"');
    expect(html).toContain('type: "comment-activate"');
    expect(html).toContain('d.type === "clear-text-selection"');
  });

  it.each([
    ["button labels", "<button><span>Export</span></button>", "span", true],
    ["link labels", '<a href="/docs"><span>Docs</span></a>', "span", true],
    ["plain text", "<p><span>Summary</span></p>", "span", false],
  ])(
    "identifies %s before activating a comment highlight",
    (_name, html, selector, expected) => {
      expect(
        isInteractiveCanvasCommentTarget(clickTarget(html, selector)),
      ).toBe(expected);
    },
  );
});

describe("resolveExternalAnchorUrl", () => {
  it("resolves a click inside a target=_blank anchor to its absolute URL", () => {
    const target = clickTarget(
      '<a href="https://posthog.com/docs" target="_blank"><span>docs</span></a>',
      "span",
    );
    expect(resolveExternalAnchorUrl(target)).toBe("https://posthog.com/docs");
  });

  it("matches the _blank keyword case-insensitively", () => {
    const target = clickTarget(
      '<a href="https://posthog.com" target="_Blank">x</a>',
      "a",
    );
    expect(resolveExternalAnchorUrl(target)).toBe("https://posthog.com/");
  });

  it("resolves SVG anchors via the href attribute", () => {
    const target = clickTarget(
      '<svg><a href="https://posthog.com" target="_blank"><text>x</text></a></svg>',
      "text",
    );
    expect(resolveExternalAnchorUrl(target)).toBe("https://posthog.com/");
  });

  it.each([
    {
      name: "anchors without target=_blank",
      html: '<a href="https://posthog.com">x</a>',
      selector: "a",
    },
    {
      name: "relative hrefs (would resolve against the host base URL)",
      html: '<a href="/settings" target="_blank">x</a>',
      selector: "a",
    },
    {
      name: "empty hrefs",
      html: '<a href="" target="_blank">x</a>',
      selector: "a",
    },
    {
      name: "clicks outside any anchor",
      html: "<button>x</button>",
      selector: "button",
    },
  ])("returns null for $name", ({ html, selector }) => {
    expect(resolveExternalAnchorUrl(clickTarget(html, selector))).toBeNull();
  });

  it("returns null for non-Element targets", () => {
    expect(resolveExternalAnchorUrl(null)).toBeNull();
    expect(resolveExternalAnchorUrl(document.createTextNode("x"))).toBeNull();
  });
});

// jsdom ships no types and this workspace does not install @types/jsdom, but
// the posthog repo root does, and local runs pick it up through node_modules
// traversal. The import is untyped only in workspace-only installs (CI), so an
// expect-error directive would be "unused" locally; only a ts-ignore fits both.
// biome-ignore lint/suspicious/noTsIgnore: the auto-fix (an expect-error directive) breaks repo-root installs (see above)
// @ts-ignore
import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";
import { injectArtifactHtmlCommentBridge } from "./artifactHtmlCommentBridge";
import { COMMENT_ACTION_BUTTON_THEMES } from "./selectionCommentAction";

const CHANNEL = "test-channel";
const BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

function loadBridgeDocument(
  html: string,
  theme: "light" | "dark" = "light",
): JSDOM {
  const dom = new JSDOM(
    injectArtifactHtmlCommentBridge(html, { channel: CHANNEL, theme }),
    {
      runScripts: "dangerously",
      url: "https://localhost/",
    },
  );
  // jsdom collapses layout boxes to zero; the bridge hides the action for
  // zero-size ranges, which real documents never produce for text selections.
  dom.window.Range.prototype.getBoundingClientRect = () =>
    ({
      top: 40,
      left: 10,
      right: 110,
      bottom: 60,
      width: 100,
      height: 20,
    }) as DOMRect;
  dom.window.Range.prototype.getClientRects = function () {
    return [this.getBoundingClientRect()] as unknown as DOMRectList;
  };
  return dom;
}

function selectParagraph(dom: JSDOM): void {
  const selection = dom.window.getSelection();
  const paragraph = dom.window.document.querySelector("p");
  if (!selection || !paragraph) throw new Error("test document needs a <p>");
  const range = dom.window.document.createRange();
  range.selectNodeContents(paragraph);
  selection.addRange(range);
}

function pressOn(dom: JSDOM, selector: string): void {
  const element = dom.window.document.querySelector(selector);
  if (!element) throw new Error(`missing ${selector}`);
  element.dispatchEvent(
    new dom.window.MouseEvent("pointerdown", { bubbles: true }),
  );
}

function releaseOn(dom: JSDOM, selector: string): void {
  const element = dom.window.document.querySelector(selector);
  if (!element) throw new Error(`missing ${selector}`);
  element.dispatchEvent(
    new dom.window.MouseEvent("pointerup", { bubbles: true }),
  );
}

function actionHost(dom: JSDOM): HTMLElement | null {
  return dom.window.document.querySelector<HTMLElement>(
    "[data-selection-comment-overlay]",
  );
}

function actionButton(dom: JSDOM): HTMLElement | null {
  return (
    actionHost(dom)?.shadowRoot?.querySelector<HTMLElement>(
      ".ph-comment-action-button",
    ) ?? null
  );
}

function pressAction(dom: JSDOM): void {
  const element = actionButton(dom);
  if (!element) throw new Error("missing comment action");
  element.dispatchEvent(
    new dom.window.MouseEvent("pointerdown", { bubbles: true, composed: true }),
  );
}

function activateAction(dom: JSDOM): void {
  const element = actionButton(dom);
  if (!element) throw new Error("missing comment action");
  element.dispatchEvent(
    new dom.window.MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      composed: true,
      detail: 1,
    }),
  );
}

describe("artifactHtmlCommentBridge", () => {
  it("shows the comment action only after the selection settles, not mid-drag", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>some selectable text here</p></body></html>",
    );

    pressOn(dom, "p");
    selectParagraph(dom);
    dom.window.document.dispatchEvent(new dom.window.Event("selectionchange"));
    expect(actionButton(dom)?.style.display ?? "none").toBe("none");

    releaseOn(dom, "p");
    expect(actionButton(dom)?.style.display).toBe("flex");
    expect(actionButton(dom)?.textContent).toBe("Comment");
    // Anchored right of the selection end (110 + 8), centered on the end
    // line (50 - 14).
    expect(actionButton(dom)?.style.left).toBe("118px");
    expect(actionButton(dom)?.style.top).toBe("36px");
    dom.window.close();
  });

  it("keeps artifact styles from targeting the comment action or its host", () => {
    const dom = loadBridgeDocument(
      '<html><head><style>button,posthog-comment-action{all:unset!important;display:none!important}</style></head><body><button id="artifact-button">Artifact</button><p>some selectable text here</p></body></html>',
    );

    pressOn(dom, "p");
    selectParagraph(dom);
    releaseOn(dom, "p");

    const host = actionHost(dom);
    const button = actionButton(dom);
    if (!host || !button) throw new Error("missing isolated comment action");
    expect(button.getRootNode()).toBe(host.shadowRoot);
    expect(dom.window.getComputedStyle(host).display).toBe("block");
    expect(dom.window.document.querySelectorAll("button")).toHaveLength(1);
    expect(host.shadowRoot?.querySelector("style")?.textContent).toContain(
      ".ph-comment-action-button",
    );
    dom.window.close();
  });

  it("ignores presses on the action button itself", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>some selectable text here</p></body></html>",
    );

    pressOn(dom, "p");
    selectParagraph(dom);
    releaseOn(dom, "p");
    expect(actionButton(dom)?.style.display).toBe("flex");

    pressAction(dom);
    expect(actionButton(dom)?.style.display).toBe("flex");
    dom.window.close();
  });

  it("posts the selected anchor and action position when activated", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>some selectable text here</p></body></html>",
    );
    const messages: unknown[] = [];
    dom.window.postMessage = ((message: unknown) => {
      messages.push(message);
    }) as typeof dom.window.postMessage;

    pressOn(dom, "p");
    selectParagraph(dom);
    releaseOn(dom, "p");
    pressAction(dom);
    dom.window.getSelection()?.removeAllRanges();
    activateAction(dom);

    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      marker: BRIDGE_MARKER,
      channel: CHANNEL,
      type: "selection",
      anchor: {
        kind: "text",
        quote: "some selectable text here",
        start: 0,
        end: 25,
      },
      rect: {
        top: 40,
        left: 10,
        right: 110,
        bottom: 60,
        width: 100,
        height: 20,
      },
      triggerRect: {
        top: expect.any(Number),
        left: expect.any(Number),
        right: expect.any(Number),
        bottom: expect.any(Number),
        width: expect.any(Number),
        height: expect.any(Number),
      },
    });
    expect(actionButton(dom)?.style.display).toBe("none");
    dom.window.close();
  });

  it("updates the active composer position when the artifact scrolls", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>some selectable text here</p></body></html>",
    );
    const messages: Array<Record<string, unknown>> = [];
    dom.window.postMessage = ((message: Record<string, unknown>) => {
      messages.push(message);
    }) as typeof dom.window.postMessage;

    pressOn(dom, "p");
    selectParagraph(dom);
    const range = dom.window.getSelection()?.getRangeAt(0);
    if (!range) throw new Error("missing selected range");
    let top = 50;
    range.getClientRects = () =>
      [
        {
          top,
          left: 70,
          right: 110,
          bottom: top + 10,
          width: 40,
          height: 10,
        },
      ] as unknown as DOMRectList;
    releaseOn(dom, "p");
    pressAction(dom);
    dom.window.getSelection()?.removeAllRanges();
    activateAction(dom);

    top = 20;
    dom.window.document.dispatchEvent(new dom.window.Event("scroll"));

    expect(messages.at(-1)).toMatchObject({
      type: "selection-position",
      rect: { top: 20, right: 110, bottom: 30 },
    });
    const positionCount = messages.filter(
      (message) => message.type === "selection-position",
    ).length;

    dom.window.dispatchEvent(
      new dom.window.MessageEvent("message", {
        data: {
          marker: BRIDGE_MARKER,
          channel: CHANNEL,
          type: "selection-dismissed",
        },
        source: dom.window as unknown as MessageEventSource,
      }),
    );
    top = 10;
    dom.window.document.dispatchEvent(new dom.window.Event("scroll"));

    expect(
      messages.filter((message) => message.type === "selection-position"),
    ).toHaveLength(positionCount);
    dom.window.close();
  });

  it("locates each navigation request only once", () => {
    const dom = loadBridgeDocument("<html><body><p>text</p></body></html>");
    const scrollIntoView = vi.fn();
    dom.window.Element.prototype.scrollIntoView = scrollIntoView;
    const send = (data: Record<string, unknown>) =>
      dom.window.dispatchEvent(
        new dom.window.MessageEvent("message", {
          data: { marker: BRIDGE_MARKER, channel: CHANNEL, ...data },
          source: dom.window as unknown as MessageEventSource,
        }),
      );

    send({
      type: "comments",
      items: [
        {
          id: "comment-1",
          anchor: {
            kind: "text",
            quote: "text",
            prefix: "",
            suffix: "",
            start: 0,
            end: 4,
          },
        },
      ],
    });
    send({ type: "locate", id: "comment-1", nonce: 1 });
    send({ type: "locate", id: "comment-1", nonce: 1 });
    send({ type: "locate", id: "comment-1", nonce: 2 });

    expect(scrollIntoView).toHaveBeenCalledTimes(2);
    dom.window.close();
  });

  it.each(["light", "dark"] as const)(
    "applies the %s theme to the isolated comment action",
    (theme) => {
      const dom = loadBridgeDocument(
        "<html><body><p>text</p></body></html>",
        theme,
      );
      pressOn(dom, "p");
      selectParagraph(dom);
      releaseOn(dom, "p");

      expect(
        actionButton(dom)?.style.getPropertyValue("--ph-comment-action-bg"),
      ).toBe(COMMENT_ACTION_BUTTON_THEMES[theme].background);
      dom.window.close();
    },
  );

  it("uses host theme changes before and after the action is created", () => {
    const dom = loadBridgeDocument(
      "<html><body><p>text</p></body></html>",
      "light",
    );
    const sendTheme = (theme: "light" | "dark") => {
      // jsdom's postMessage leaves event.source null; the bridge ignores those.
      dom.window.dispatchEvent(
        new dom.window.MessageEvent("message", {
          data: {
            marker: BRIDGE_MARKER,
            channel: CHANNEL,
            type: "theme",
            theme,
          },
          source: dom.window as unknown as MessageEventSource,
        }),
      );
    };

    sendTheme("dark");
    pressOn(dom, "p");
    selectParagraph(dom);
    releaseOn(dom, "p");
    expect(
      actionButton(dom)?.style.getPropertyValue("--ph-comment-action-bg"),
    ).toBe(COMMENT_ACTION_BUTTON_THEMES.dark.background);

    sendTheme("light");
    expect(
      actionButton(dom)?.style.getPropertyValue("--ph-comment-action-bg"),
    ).toBe(COMMENT_ACTION_BUTTON_THEMES.light.background);
    dom.window.close();
  });
});

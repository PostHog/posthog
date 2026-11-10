import * as fs from "node:fs";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { PostHogEnricher } from "./enricher.js";
import type { LocalWrapper } from "./types.js";

const GRAMMARS_DIR = path.join(__dirname, "..", "grammars");
const hasGrammars = fs.existsSync(
  path.join(GRAMMARS_DIR, "tree-sitter-javascript.wasm"),
);
const describeWithGrammars = hasGrammars ? describe : describe.skip;

async function buildContext(
  enricher: PostHogEnricher,
  source: string,
  langId: string,
  callerAbsPath: string,
): Promise<{
  wrappersByLocalName: Map<string, LocalWrapper>;
  namespaceWrappers: Map<string, Map<string, LocalWrapper>>;
}> {
  const edges = await enricher.findImportsInSource(
    source,
    langId,
    callerAbsPath,
  );
  const wrappersByLocalName = new Map<string, LocalWrapper>();
  const namespaceWrappers = new Map<string, Map<string, LocalWrapper>>();
  for (const edge of edges) {
    if (!edge.resolvedAbsPath) continue;
    const wrappers = await enricher.getWrappersForFile(edge.resolvedAbsPath);
    if (!wrappers.length) continue;

    if (edge.isNamespace) {
      const nsMap = new Map<string, LocalWrapper>();
      for (const w of wrappers) {
        if (w.isNamedExport || w.isDefaultExport) nsMap.set(w.name, w);
      }
      if (nsMap.size) namespaceWrappers.set(edge.localName, nsMap);
      continue;
    }
    if (edge.isDefault) {
      const target = wrappers.find((w) => w.isDefaultExport);
      if (target) wrappersByLocalName.set(edge.localName, target);
      continue;
    }
    const target = wrappers.find(
      (w) => w.name === edge.importedName && w.isNamedExport,
    );
    if (target) wrappersByLocalName.set(edge.localName, target);
  }
  return { wrappersByLocalName, namespaceWrappers };
}

describeWithGrammars("Wrapper-aware enrichment (cross-file)", () => {
  let enricher: PostHogEnricher;
  let workDir: string;

  beforeAll(() => {
    enricher = new PostHogEnricher();
    workDir = mkdtempSync(path.join(tmpdir(), "enricher-wrapper-"));
  });

  afterAll(() => {
    enricher.dispose();
    fs.rmSync(workDir, { recursive: true, force: true });
  });

  test("JS named import of pass-through wrapper synthesizes PostHogCall", async () => {
    const tracker = path.join(workDir, "telemetry.ts");
    writeFileSync(
      tracker,
      `export function track(event, props) {\n  posthog.capture(event, props);\n}\n`,
    );

    const app = path.join(workDir, "app.ts");
    const appSrc = `import { track } from "./telemetry";\ntrack("checkout_completed");\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    expect(ctx.wrappersByLocalName.has("track")).toBe(true);

    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.calls).toHaveLength(1);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      key: "checkout_completed",
      viaWrapper: "track",
    });
  });

  test("JS default import of wrapper synthesizes PostHogCall", async () => {
    const tracker = path.join(workDir, "default-tel.ts");
    writeFileSync(
      tracker,
      `export default function track(event) {\n  posthog.capture(event);\n}\n`,
    );

    const app = path.join(workDir, "app-default.ts");
    const appSrc = `import track from "./default-tel";\ntrack("signup");\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      key: "signup",
      viaWrapper: "track",
    });
  });

  test("JS namespace import of wrapper synthesizes PostHogCall", async () => {
    const tracker = path.join(workDir, "ns-tel.ts");
    writeFileSync(
      tracker,
      `export function track(event) {\n  posthog.capture(event);\n}\n`,
    );

    const app = path.join(workDir, "app-ns.ts");
    const appSrc = `import * as tel from "./ns-tel";\ntel.track("event_via_ns");\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    expect(ctx.namespaceWrappers.has("tel")).toBe(true);

    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      key: "event_via_ns",
      viaWrapper: "track",
    });
  });

  test("fixed-key wrapper produces the baked-in key", async () => {
    const tracker = path.join(workDir, "fixed-tel.ts");
    writeFileSync(
      tracker,
      `export function trackPurchase(data) {\n  posthog.capture("purchase", data);\n}\n`,
    );

    const app = path.join(workDir, "app-fixed.ts");
    const appSrc = `import { trackPurchase } from "./fixed-tel";\ntrackPurchase({ amount: 42 });\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      key: "purchase",
      viaWrapper: "trackPurchase",
    });
  });

  test("flag-method wrapper synthesizes a flag check", async () => {
    const tracker = path.join(workDir, "flag-tel.ts");
    writeFileSync(
      tracker,
      `export function useFlag(key) {\n  return posthog.isFeatureEnabled(key);\n}\n`,
    );

    const app = path.join(workDir, "app-flag.ts");
    const appSrc = `import { useFlag } from "./flag-tel";\nconst on = useFlag("new-checkout");\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.flagChecks).toHaveLength(1);
    expect(parsed.flagChecks[0]).toMatchObject({
      method: "isFeatureEnabled",
      flagKey: "new-checkout",
      viaWrapper: "useFlag",
    });
  });

  test("Python cross-file wrapper", async () => {
    const tracker = path.join(workDir, "tel.py");
    writeFileSync(
      tracker,
      `def track(distinct_id, event_name):\n    posthog.capture(distinct_id, event_name)\n`,
    );

    const app = path.join(workDir, "app.py");
    const appSrc = `from .tel import track\ntrack("user1", "payment_succeeded")\n`;

    const ctx = await buildContext(enricher, appSrc, "python", app);
    expect(ctx.wrappersByLocalName.has("track")).toBe(true);

    const parsed = await enricher.parse(appSrc, "python", ctx);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      key: "payment_succeeded",
      viaWrapper: "track",
    });
  });

  test("identifier arg resolved through constant map", async () => {
    const tracker = path.join(workDir, "const-tel.ts");
    writeFileSync(
      tracker,
      `export function track(event) {\n  posthog.capture(event);\n}\n`,
    );

    const app = path.join(workDir, "app-const.ts");
    const appSrc = `import { track } from "./const-tel";\nconst EVT = "user_signed_up";\ntrack(EVT);\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      key: "user_signed_up",
      viaWrapper: "track",
    });
  });

  test("unresolvable identifier arg marks call as dynamic", async () => {
    const tracker = path.join(workDir, "dyn-tel.ts");
    writeFileSync(
      tracker,
      `export function track(event) {\n  posthog.capture(event);\n}\n`,
    );

    const app = path.join(workDir, "app-dyn.ts");
    const appSrc = `import { track } from "./dyn-tel";\ntrack(computedEventName);\n`;

    const ctx = await buildContext(enricher, appSrc, "typescript", app);
    const parsed = await enricher.parse(appSrc, "typescript", ctx);
    expect(parsed.calls).toHaveLength(1);
    expect(parsed.calls[0]).toMatchObject({
      method: "capture",
      dynamic: true,
      viaWrapper: "track",
    });
  });

  test("wrapper registry mtime invalidates cache", async () => {
    const target = path.join(workDir, "mtime-tel.ts");
    writeFileSync(
      target,
      `export function track(event) {\n  posthog.capture(event);\n}\n`,
    );
    const first = await enricher.getWrappersForFile(target);
    expect(first.map((w) => w.name)).toEqual(["track"]);

    // Rewrite with a different wrapper; bump mtime by 2s to avoid fs resolution issues.
    writeFileSync(
      target,
      `export function log(flag) {\n  return posthog.getFeatureFlag(flag);\n}\n`,
    );
    const future = new Date(Date.now() + 2000);
    fs.utimesSync(target, future, future);

    const second = await enricher.getWrappersForFile(target);
    expect(second.map((w) => w.name)).toEqual(["log"]);
  });

  test("TSX caller with direct posthog AND wrapper call gets both synthesized", async () => {
    const utils = path.join(workDir, "utils.ts");
    writeFileSync(
      utils,
      `import posthog from "posthog-js";\nexport const track = (event_name: string) => {\n  posthog.capture(event_name);\n};\n`,
    );

    const app = path.join(workDir, "page.tsx");
    const appSrc = `"use client";
import posthog from "posthog-js";
import { track } from "./utils";

export default function Home() {
  posthog.capture("purchase_completed", { price: 99 });
  return (
    <button onClick={() => track("event_123")}>New button</button>
  );
}
`;

    // Sanity-check the building blocks first.
    const edges = await enricher.findImportsInSource(
      appSrc,
      "typescriptreact",
      app,
    );
    const trackEdge = edges.find((e) => e.localName === "track");
    expect(
      trackEdge,
      "imports to include { track } from ./utils",
    ).toBeDefined();
    expect(trackEdge?.resolvedAbsPath).toBe(utils);

    const wrappers = await enricher.getWrappersForFile(utils);
    expect(wrappers.map((w) => w.name)).toContain("track");

    const ctx = await buildContext(enricher, appSrc, "typescriptreact", app);
    expect(ctx.wrappersByLocalName.has("track")).toBe(true);

    const parsed = await enricher.parse(appSrc, "typescriptreact", ctx);
    const events = parsed.events.map((e) => ({
      name: e.name,
      viaWrapper: e.viaWrapper,
    }));
    expect(events).toEqual(
      expect.arrayContaining([
        { name: "purchase_completed", viaWrapper: undefined },
        { name: "event_123", viaWrapper: "track" },
      ]),
    );
  });

  test("wrapper call inside JSX sets inJsx and renders as JSX comment", async () => {
    const utils = path.join(workDir, "jsx-utils.ts");
    writeFileSync(
      utils,
      `import posthog from "posthog-js";\nexport const track = (event_name: string) => {\n  posthog.capture(event_name);\n};\n`,
    );

    const app = path.join(workDir, "jsx-page.tsx");
    const appSrc = `"use client";
import posthog from "posthog-js";
import { track } from "./jsx-utils";

export default function Home() {
  posthog.capture("direct_event");
  return (
    <div>
      <button onClick={() => track("event_123")}>New button</button>
    </div>
  );
}
`;

    const ctx = await buildContext(enricher, appSrc, "typescriptreact", app);
    const parsed = await enricher.parse(appSrc, "typescriptreact", ctx);

    const directCall = parsed.calls.find((c) => c.key === "direct_event");
    const wrapperCall = parsed.calls.find((c) => c.key === "event_123");
    expect(directCall?.inJsx).toBeFalsy();
    expect(wrapperCall?.inJsx).toBe(true);

    const annotated = (
      await parsed.enrichFromApi({
        apiKey: "k",
        host: "https://example.com",
        projectId: 1,
        timeoutMs: 1,
      })
    ).toInlineComments();

    // The wrapper-call line lives inside JSX, so its annotation must use a JSX-safe comment.
    const wrapperLine = annotated
      .split("\n")
      .find((l) => l.includes('track("event_123")'));
    expect(wrapperLine).toContain("{/* [PostHog]");
    expect(wrapperLine).toContain("*/}");

    // The direct call is in a JS statement context, so the existing `//` form is correct.
    const directLine = annotated
      .split("\n")
      .find((l) => l.includes('posthog.capture("direct_event")'));
    expect(directLine).toContain("// [PostHog]");
  });

  test("non-wrapper file is cached as empty", async () => {
    const target = path.join(workDir, "not-a-wrapper.ts");
    writeFileSync(target, `export function noop() {\n  return 42;\n}\n`);
    const wrappers = await enricher.getWrappersForFile(target);
    expect(wrappers).toEqual([]);
  });
});

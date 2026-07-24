import * as fs from "node:fs";
import * as path from "node:path";
import { beforeAll, describe, expect, test } from "vitest";
import { PostHogDetector } from "./detector.js";
import type { LocalWrapper } from "./types.js";

const GRAMMARS_DIR = path.join(__dirname, "..", "grammars");
const hasGrammars = fs.existsSync(
  path.join(GRAMMARS_DIR, "tree-sitter-javascript.wasm"),
);
const describeWithGrammars = hasGrammars ? describe : describe.skip;

function summary(w: LocalWrapper) {
  return {
    name: w.name,
    methodKind: w.methodKind,
    posthogMethod: w.posthogMethod,
    classification: w.classification,
    isNamedExport: w.isNamedExport ?? false,
    isDefaultExport: w.isDefaultExport ?? false,
  };
}

describeWithGrammars("findWrappers (JS/TS)", () => {
  let detector: PostHogDetector;

  beforeAll(() => {
    detector = new PostHogDetector();
  });

  test("pass-through wrapper at param 0", async () => {
    const src = `
      export function track(event, props) {
        posthog.capture(event, props);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers.map(summary)).toEqual([
      {
        name: "track",
        methodKind: "capture",
        posthogMethod: "capture",
        classification: { kind: "pass-through", paramIndex: 0 },
        isNamedExport: true,
        isDefaultExport: false,
      },
    ]);
  });

  test("pass-through wrapper at param 1", async () => {
    const src = `
      export function trackAt(ctx, eventName) {
        posthog.capture(eventName);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0].classification).toEqual({
      kind: "pass-through",
      paramIndex: 1,
    });
  });

  test("fixed-key wrapper", async () => {
    const src = `
      export function trackPurchase(data) {
        posthog.capture("purchase", data);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0].classification).toEqual({
      kind: "fixed-key",
      key: "purchase",
    });
  });

  test("flag wrapper returns methodKind=flag", async () => {
    const src = `
      export function useFlag(key) {
        return posthog.isFeatureEnabled(key);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers[0]).toMatchObject({
      name: "useFlag",
      methodKind: "flag",
      posthogMethod: "isFeatureEnabled",
      classification: { kind: "pass-through", paramIndex: 0 },
    });
  });

  test("arrow function wrapper", async () => {
    const src = `
      export const track = (event) => {
        posthog.capture(event);
      };
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0].name).toBe("track");
    expect(wrappers[0].isNamedExport).toBe(true);
  });

  test("typed arrow function wrapper (real demo shape)", async () => {
    const src = `import posthog from "posthog-js";
export const track = (event_name: string) => {
  posthog.capture(event_name);
};
`;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0]).toMatchObject({
      name: "track",
      methodKind: "capture",
      posthogMethod: "capture",
      classification: { kind: "pass-through", paramIndex: 0 },
      isNamedExport: true,
    });
  });

  test("default export wrapper", async () => {
    const src = `
      export default function track(event) {
        posthog.capture(event);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers[0]).toMatchObject({
      name: "track",
      isDefaultExport: true,
    });
  });

  test("non-exported function still detected as wrapper", async () => {
    const src = `
      function track(event) {
        posthog.capture(event);
      }
      track("hello");
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0].isNamedExport).toBe(false);
    expect(wrappers[0].isDefaultExport).toBe(false);
  });

  test("opaque body (dynamic key) is NOT registered", async () => {
    const src = `
      export function log(flavor) {
        posthog.capture(computeName(flavor));
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toEqual([]);
  });

  test("function with no PostHog call is ignored", async () => {
    const src = `
      export function noop(event) {
        console.log(event);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toEqual([]);
  });

  test("constructor-aliased client inside body still detected", async () => {
    const src = `
      const client = new PostHog("phc_x");
      export function track(event) {
        client.capture(event);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0].name).toBe("track");
  });

  test("nested wrapper: outer does not get registered when inner calls PostHog", async () => {
    const src = `
      export function outer(event) {
        function inner(e) {
          posthog.capture(e);
        }
        inner(event);
      }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    // "inner" is the wrapper; "outer" is NOT — it only calls inner.
    const names = wrappers.map((w) => w.name).sort();
    expect(names).toContain("inner");
    expect(names).not.toContain("outer");
  });

  test("multiple wrappers in one file", async () => {
    const src = `
      export function track(event) { posthog.capture(event); }
      export function useFlag(key) { return posthog.getFeatureFlag(key); }
    `;
    const wrappers = await detector.findWrappers(src, "typescript");
    expect(wrappers.map((w) => w.name).sort()).toEqual(["track", "useFlag"]);
  });
});

describeWithGrammars("findWrappers (Python)", () => {
  let detector: PostHogDetector;

  beforeAll(() => {
    detector = new PostHogDetector();
  });

  test("pass-through wrapper — event is second positional", async () => {
    const src = `
def track(distinct_id, event_name, props=None):
    posthog.capture(distinct_id, event_name, props)
`;
    const wrappers = await detector.findWrappers(src, "python");
    expect(wrappers).toHaveLength(1);
    expect(wrappers[0]).toMatchObject({
      name: "track",
      posthogMethod: "capture",
      classification: { kind: "pass-through", paramIndex: 1 },
    });
  });

  test("fixed-key wrapper", async () => {
    const src = `
def track_purchase(data):
    posthog.capture("user1", "purchase", data)
`;
    const wrappers = await detector.findWrappers(src, "python");
    expect(wrappers[0].classification).toEqual({
      kind: "fixed-key",
      key: "purchase",
    });
  });

  test("flag wrapper using get_feature_flag", async () => {
    const src = `
def use_flag(key):
    return posthog.get_feature_flag(key)
`;
    const wrappers = await detector.findWrappers(src, "python");
    expect(wrappers[0]).toMatchObject({
      name: "use_flag",
      methodKind: "flag",
      posthogMethod: "get_feature_flag",
      classification: { kind: "pass-through", paramIndex: 0 },
    });
  });

  test("event=keyword argument also counts as key arg", async () => {
    const src = `
def track(event_name):
    posthog.capture(distinct_id="u", event=event_name)
`;
    const wrappers = await detector.findWrappers(src, "python");
    expect(wrappers[0].classification).toEqual({
      kind: "pass-through",
      paramIndex: 0,
    });
  });
});

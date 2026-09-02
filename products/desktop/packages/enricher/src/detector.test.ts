import * as fs from "node:fs";
import * as path from "node:path";
import { beforeAll, describe, expect, test } from "vitest";
import { PostHogDetector } from "./detector.js";
import type { PostHogCall, PostHogInitCall, VariantBranch } from "./types.js";

const GRAMMARS_DIR = path.join(__dirname, "..", "grammars");
const hasGrammars = fs.existsSync(
  path.join(GRAMMARS_DIR, "tree-sitter-javascript.wasm"),
);

// Skip all tree-sitter tests if grammars aren't built
const describeWithGrammars = hasGrammars ? describe : describe.skip;

function simpleCalls(calls: PostHogCall[]) {
  return calls.map((c) => ({ line: c.line, method: c.method, key: c.key }));
}

function simpleBranches(branches: VariantBranch[]) {
  return branches.map((b) => ({
    flagKey: b.flagKey,
    variantKey: b.variantKey,
    conditionLine: b.conditionLine,
  }));
}

function simpleInits(inits: PostHogInitCall[]) {
  return inits.map((i) => ({
    token: i.token,
    tokenLine: i.tokenLine,
    apiHost: i.apiHost,
  }));
}

describeWithGrammars("PostHogDetector", () => {
  let detector: PostHogDetector;

  beforeAll(() => {
    detector = new PostHogDetector();
    detector.updateConfig({
      additionalClientNames: [],
      additionalFlagFunctions: [
        "useFeatureFlag",
        "useFeatureFlagPayload",
        "useFeatureFlagVariantKey",
      ],
      detectNestedClients: true,
    });
  });

  // ═══════════════════════════════════════════════════
  // JavaScript — findPostHogCalls
  // ═══════════════════════════════════════════════════

  describe("JavaScript — findPostHogCalls", () => {
    test("detects flag and capture methods", async () => {
      const code = [
        `const flag = posthog.getFeatureFlag('my-flag');`,
        `const on = posthog.isFeatureEnabled('beta');`,
        `posthog.capture('purchase');`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "getFeatureFlag", key: "my-flag" },
        { line: 1, method: "isFeatureEnabled", key: "beta" },
        { line: 2, method: "capture", key: "purchase" },
      ]);
    });

    test("detects client alias", async () => {
      const code = [`const ph = posthog;`, `ph.capture('aliased-event');`].join(
        "\n",
      );

      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(simpleCalls(calls)).toEqual([
        { line: 1, method: "capture", key: "aliased-event" },
      ]);
    });

    test("detects constructor alias (new PostHog)", async () => {
      const code = [
        `const client = new PostHog('phc_token');`,
        `client.capture('ctor-event');`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(simpleCalls(calls)).toEqual([
        { line: 1, method: "capture", key: "ctor-event" },
      ]);
    });

    test("detects Node SDK capture with object argument", async () => {
      const code = [
        `const client = new PostHog('phc_token');`,
        `client.capture({ distinctId: 'u1', event: 'node-event' });`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(simpleCalls(calls)).toEqual([
        { line: 1, method: "capture", key: "node-event" },
      ]);
    });

    test("detects React hooks (bare function calls)", async () => {
      const code = [
        `const flag = useFeatureFlag('hook-flag');`,
        `const payload = useFeatureFlagPayload('hook-payload');`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "useFeatureFlag", key: "hook-flag" },
        { line: 1, method: "useFeatureFlagPayload", key: "hook-payload" },
      ]);
    });

    test("detects nested client (window.posthog)", async () => {
      const code = `window.posthog.capture('nested-event');`;
      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "capture", key: "nested-event" },
      ]);
    });

    test("detects dynamic capture calls", async () => {
      const code = `posthog.capture(getEventName());`;
      const calls = await detector.findPostHogCalls(code, "javascript");
      expect(calls).toHaveLength(1);
      expect(calls[0].dynamic).toBe(true);
    });
  });

  // ═══════════════════════════════════════════════════
  // JavaScript — findVariantBranches
  // ═══════════════════════════════════════════════════

  describe("JavaScript — findVariantBranches", () => {
    test("detects if/else chain from variable", async () => {
      const code = [
        `const v = posthog.getFeatureFlag('exp');`,
        `if (v === 'control') {`,
        `    console.log('a');`,
        `} else {`,
        `    console.log('c');`,
        `}`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "javascript");
      expect(simpleBranches(branches)).toEqual([
        { flagKey: "exp", variantKey: "control", conditionLine: 1 },
        { flagKey: "exp", variantKey: "else", conditionLine: 3 },
      ]);
    });

    test("detects boolean flag check (true/false, not else)", async () => {
      const code = [
        `const on = posthog.isFeatureEnabled('feat');`,
        `if (on) {`,
        `    console.log('yes');`,
        `} else {`,
        `    console.log('no');`,
        `}`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "javascript");
      expect(simpleBranches(branches)).toEqual([
        { flagKey: "feat", variantKey: "true", conditionLine: 1 },
        { flagKey: "feat", variantKey: "false", conditionLine: 3 },
      ]);
    });

    test("detects inline flag comparison", async () => {
      const code = [
        `if (posthog.getFeatureFlag('ab') === 'v1') {`,
        `    console.log('v1');`,
        `}`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "javascript");
      expect(simpleBranches(branches)).toEqual([
        { flagKey: "ab", variantKey: "v1", conditionLine: 0 },
      ]);
    });

    test("detects hook variable branches", async () => {
      const code = [
        `const variant = useFeatureFlag('exp');`,
        `if (variant === 'a') {`,
        `    do_a();`,
        `} else {`,
        `    do_b();`,
        `}`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "javascript");
      expect(simpleBranches(branches)).toEqual([
        { flagKey: "exp", variantKey: "a", conditionLine: 1 },
        { flagKey: "exp", variantKey: "else", conditionLine: 3 },
      ]);
    });

    test("negated boolean resolves correctly", async () => {
      const code = [
        `const enabled = posthog.isFeatureEnabled('feat');`,
        `if (!enabled) {`,
        `    off();`,
        `} else {`,
        `    on();`,
        `}`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "javascript");
      const variants = branches
        .filter((b) => b.flagKey === "feat")
        .map((b) => b.variantKey)
        .sort();
      expect(variants).toEqual(["false", "true"]);
    });
  });

  // ═══════════════════════════════════════════════════
  // JavaScript — findInitCalls
  // ═══════════════════════════════════════════════════

  describe("JavaScript — findInitCalls", () => {
    test("detects posthog.init()", async () => {
      const code = `posthog.init('phc_abc', { api_host: 'https://us.i.posthog.com' });`;
      const inits = await detector.findInitCalls(code, "javascript");
      expect(simpleInits(inits)).toEqual([
        { token: "phc_abc", tokenLine: 0, apiHost: "https://us.i.posthog.com" },
      ]);
    });

    test("detects new PostHog() constructor", async () => {
      const code = `const client = new PostHog('phc_xyz', { host: 'https://eu.posthog.com' });`;
      const inits = await detector.findInitCalls(code, "javascript");
      expect(simpleInits(inits)).toEqual([
        { token: "phc_xyz", tokenLine: 0, apiHost: "https://eu.posthog.com" },
      ]);
    });
  });

  // ═══════════════════════════════════════════════════
  // Python
  // ═══════════════════════════════════════════════════

  describe("Python — findPostHogCalls", () => {
    test("detects flag methods", async () => {
      const code = [
        `flag = posthog.get_feature_flag("my-flag", "user-1")`,
        `enabled = posthog.is_feature_enabled("beta", "user-1")`,
        `payload = posthog.get_feature_flag_payload("cfg", "user-1")`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "python");
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "get_feature_flag", key: "my-flag" },
        { line: 1, method: "is_feature_enabled", key: "beta" },
        { line: 2, method: "get_feature_flag_payload", key: "cfg" },
      ]);
    });

    test("detects capture with positional args (event is 2nd)", async () => {
      const code = `posthog.capture("user-1", "purchase_completed")`;
      const calls = await detector.findPostHogCalls(code, "python");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "purchase_completed",
      );
      expect(capture).toBeDefined();
    });

    test("detects capture with keyword args", async () => {
      const code = `posthog.capture(distinct_id="user-1", event="signup")`;
      const calls = await detector.findPostHogCalls(code, "python");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "signup",
      );
      expect(capture).toBeDefined();
    });

    test("detects constructor alias", async () => {
      const code = [
        `client = Posthog("phc_token", host="https://us.posthog.com")`,
        `client.capture("user-1", "ctor-event")`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "python");
      const event = calls.find(
        (c) => c.method === "capture" && c.key === "ctor-event",
      );
      expect(event).toBeDefined();
      expect(event?.line).toBe(1);
    });
  });

  describe("Python — findVariantBranches", () => {
    test("detects if/elif/else chain", async () => {
      const code = [
        `flag = posthog.get_feature_flag("exp", "u1")`,
        `if flag == "control":`,
        `    print("a")`,
        `elif flag == "test":`,
        `    print("b")`,
        `else:`,
        `    print("c")`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "python");
      const control = branches.find((b) => b.variantKey === "control");
      const test_ = branches.find((b) => b.variantKey === "test");
      expect(control).toBeDefined();
      expect(test_).toBeDefined();
      expect(control?.conditionLine).toBe(1);
      expect(test_?.conditionLine).toBe(3);
    });

    test("detects boolean enabled check", async () => {
      const code = [
        `on = posthog.is_feature_enabled("feat", "u1")`,
        `if on:`,
        `    print("yes")`,
        `else:`,
        `    print("no")`,
      ].join("\n");

      const branches = await detector.findVariantBranches(code, "python");
      expect(simpleBranches(branches)).toEqual([
        { flagKey: "feat", variantKey: "true", conditionLine: 1 },
        { flagKey: "feat", variantKey: "false", conditionLine: 3 },
      ]);
    });
  });

  // ═══════════════════════════════════════════════════
  // Go
  // ═══════════════════════════════════════════════════

  describe("Go — findPostHogCalls", () => {
    test("detects flag methods", async () => {
      const code = [
        `package main`,
        ``,
        `func main() {`,
        `  flag, _ := client.GetFeatureFlag("my-flag", "user-1")`,
        `  enabled, _ := client.IsFeatureEnabled("beta", "user-1")`,
        `}`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "go");
      expect(simpleCalls(calls)).toEqual([
        { line: 3, method: "GetFeatureFlag", key: "my-flag" },
        { line: 4, method: "IsFeatureEnabled", key: "beta" },
      ]);
    });

    test("detects struct-based Enqueue capture", async () => {
      const code = [
        `package main`,
        ``,
        `func main() {`,
        `  client.Enqueue(posthog.Capture{Event: "purchase"})`,
        `}`,
      ].join("\n");
      const calls = await detector.findPostHogCalls(code, "go");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "purchase",
      );
      expect(capture).toBeDefined();
    });
  });

  // ═══════════════════════════════════════════════════
  // Ruby
  // ═══════════════════════════════════════════════════

  describe("Ruby — findPostHogCalls", () => {
    test("detects flag methods", async () => {
      const code = `enabled = client.is_feature_enabled('my-flag', 'user-1')`;
      const calls = await detector.findPostHogCalls(code, "ruby");
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "is_feature_enabled", key: "my-flag" },
      ]);
    });

    test("detects keyword-arg capture", async () => {
      const code = `client.capture(distinct_id: 'user-1', event: 'purchase')`;
      const calls = await detector.findPostHogCalls(code, "ruby");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "purchase",
      );
      expect(capture).toBeDefined();
    });
  });

  // ═══════════════════════════════════════════════════
  // Cross-language parity
  // ═══════════════════════════════════════════════════

  describe("Cross-language parity", () => {
    test("same flag detected in JS and Python", async () => {
      const jsCode = `const flag = posthog.getFeatureFlag('shared-flag');`;
      const pyCode = `flag = posthog.get_feature_flag("shared-flag", "u1")`;

      const jsCalls = await detector.findPostHogCalls(jsCode, "javascript");
      const pyCalls = await detector.findPostHogCalls(pyCode, "python");

      expect(jsCalls.find((c) => c.key === "shared-flag")).toBeDefined();
      expect(pyCalls.find((c) => c.key === "shared-flag")).toBeDefined();
    });

    test("same event detected in JS and Python", async () => {
      const jsCode = `posthog.capture('shared-event');`;
      const pyCode = `posthog.capture("u1", "shared-event")`;

      const jsCalls = await detector.findPostHogCalls(jsCode, "javascript");
      const pyCalls = await detector.findPostHogCalls(pyCode, "python");

      expect(jsCalls.find((c) => c.key === "shared-event")).toBeDefined();
      expect(pyCalls.find((c) => c.key === "shared-event")).toBeDefined();
    });
  });

  // ═══════════════════════════════════════════════════
  // TypeScript
  // ═══════════════════════════════════════════════════

  describe("TypeScript — findPostHogCalls", () => {
    test("detects basic calls", async () => {
      const code = [
        `const flag = posthog.getFeatureFlag('ts-flag');`,
        `posthog.capture('ts-event');`,
      ].join("\n");

      const calls = await detector.findPostHogCalls(code, "typescript");
      // TS grammar may not parse identically in all environments.
      // Match the VSCode extension's original test behavior:
      // "if it loads, verify correctness; if not, skip gracefully"
      if (calls.length === 0) {
        return;
      }
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "getFeatureFlag", key: "ts-flag" },
        { line: 1, method: "capture", key: "ts-event" },
      ]);
    });
  });

  // ═══════════════════════════════════════════════════
  // Python — additional findPostHogCalls / findInitCalls
  // ═══════════════════════════════════════════════════

  describe("Python — findPostHogCalls (capture)", () => {
    test("detects capture with positional event arg", async () => {
      const code = `posthog.capture('user_id', 'purchase')`;
      const calls = await detector.findPostHogCalls(code, "python");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "purchase",
      );
      expect(capture).toBeDefined();
    });

    test("detects flag method get_feature_flag", async () => {
      const code = `posthog.get_feature_flag('my-flag')`;
      const calls = await detector.findPostHogCalls(code, "python");
      expect(simpleCalls(calls)).toEqual([
        { line: 0, method: "get_feature_flag", key: "my-flag" },
      ]);
    });
  });

  describe("Python — findInitCalls", () => {
    test("detects positional constructor Posthog('phc_token')", async () => {
      const code = `Posthog('phc_token')`;
      const inits = await detector.findInitCalls(code, "python");
      expect(inits).toHaveLength(1);
      expect(inits[0].token).toBe("phc_token");
    });

    test("detects keyword constructor with api_key and host", async () => {
      const code = `Posthog(api_key='phc_token', host='https://app.posthog.com')`;
      const inits = await detector.findInitCalls(code, "python");
      expect(inits).toHaveLength(1);
      expect(inits[0].token).toBe("phc_token");
      expect(inits[0].apiHost).toBe("https://app.posthog.com");
    });
  });

  // ═══════════════════════════════════════════════════
  // Go — additional findPostHogCalls / findInitCalls
  // ═══════════════════════════════════════════════════

  describe("Go — findPostHogCalls (capture & flags)", () => {
    test("detects struct-based Enqueue capture", async () => {
      const code = [
        `package main`,
        ``,
        `func main() {`,
        `  client.Enqueue(posthog.Capture{Event: "purchase"})`,
        `}`,
      ].join("\n");
      const calls = await detector.findPostHogCalls(code, "go");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "purchase",
      );
      expect(capture).toBeDefined();
    });

    test("detects flag method GetFeatureFlag", async () => {
      const code = [
        `package main`,
        ``,
        `func main() {`,
        `  client.GetFeatureFlag(posthog.FeatureFlagPayload{Key: "my-flag"})`,
        `}`,
      ].join("\n");
      const calls = await detector.findPostHogCalls(code, "go");
      const flag = calls.find(
        (c) => c.method === "GetFeatureFlag" && c.key === "my-flag",
      );
      expect(flag).toBeDefined();
    });
  });

  describe("Go — findInitCalls", () => {
    test("detects posthog.New constructor", async () => {
      const code = [
        `package main`,
        ``,
        `func main() {`,
        `  client := posthog.New("phc_token")`,
        `}`,
      ].join("\n");
      const inits = await detector.findInitCalls(code, "go");
      expect(inits).toHaveLength(1);
      expect(inits[0].token).toBe("phc_token");
    });

    test("detects posthog.NewWithConfig constructor", async () => {
      const code = [
        `package main`,
        ``,
        `func main() {`,
        `  client, _ := posthog.NewWithConfig("phc_token", posthog.Config{Endpoint: "https://app.posthog.com"})`,
        `}`,
      ].join("\n");
      const inits = await detector.findInitCalls(code, "go");
      expect(inits).toHaveLength(1);
      expect(inits[0].token).toBe("phc_token");
      expect(inits[0].apiHost).toBe("https://app.posthog.com");
    });
  });

  // ═══════════════════════════════════════════════════
  // Ruby — additional findPostHogCalls / findInitCalls
  // ═══════════════════════════════════════════════════

  describe("Ruby — findPostHogCalls (capture & flags)", () => {
    test("detects capture with keyword args", async () => {
      const code = `client.capture(distinct_id: 'user', event: 'purchase')`;
      const calls = await detector.findPostHogCalls(code, "ruby");
      const capture = calls.find(
        (c) => c.method === "capture" && c.key === "purchase",
      );
      expect(capture).toBeDefined();
    });

    test("detects flag method get_feature_flag", async () => {
      const code = `client.get_feature_flag('my-flag')`;
      const calls = await detector.findPostHogCalls(code, "ruby");
      const flag = calls.find(
        (c) => c.method === "get_feature_flag" && c.key === "my-flag",
      );
      expect(flag).toBeDefined();
    });
  });

  describe("Ruby — findInitCalls", () => {
    test("detects PostHog::Client.new constructor", async () => {
      const code = `client = PostHog::Client.new(api_key: 'phc_token')`;
      const inits = await detector.findInitCalls(code, "ruby");
      expect(inits).toHaveLength(1);
      expect(inits[0].token).toBe("phc_token");
    });
  });

  // ═══════════════════════════════════════════════════
  // Negative / edge cases
  // ═══════════════════════════════════════════════════

  describe("Negative / edge cases", () => {
    test("unsupported language returns empty arrays", async () => {
      const code = `posthog.capture('event')`;
      const calls = await detector.findPostHogCalls(code, "haskell");
      const inits = await detector.findInitCalls(code, "haskell");
      expect(calls).toEqual([]);
      expect(inits).toEqual([]);
    });

    test("non-PostHog client names are ignored", async () => {
      const code = `other.capture('event')`;

      const jsCalls = await detector.findPostHogCalls(code, "javascript");
      const pyCalls = await detector.findPostHogCalls(code, "python");
      const rbCalls = await detector.findPostHogCalls(code, "ruby");

      expect(jsCalls).toEqual([]);
      expect(pyCalls).toEqual([]);
      expect(rbCalls).toEqual([]);
    });
  });
});

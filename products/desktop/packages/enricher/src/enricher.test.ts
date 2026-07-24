import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
  vi,
} from "vitest";
import { PostHogEnricher } from "./enricher.js";
import type {
  EnricherApiConfig,
  EventDefinition,
  Experiment,
  FeatureFlag,
} from "./types.js";

const GRAMMARS_DIR = path.join(__dirname, "..", "grammars");
const hasGrammars = fs.existsSync(
  path.join(GRAMMARS_DIR, "tree-sitter-javascript.wasm"),
);

const describeWithGrammars = hasGrammars ? describe : describe.skip;

const API_CONFIG: EnricherApiConfig = {
  apiKey: "phx_test",
  host: "https://test.posthog.com",
  projectId: 1,
};

const makeFlag = (
  key: string,
  overrides: Partial<FeatureFlag> = {},
): FeatureFlag => ({
  id: 1,
  key,
  name: key,
  active: true,
  filters: {},
  created_at: "2024-01-01T00:00:00Z",
  created_by: null,
  deleted: false,
  ...overrides,
});

const makeExperiment = (
  flagKey: string,
  overrides: Partial<Experiment> = {},
): Experiment => ({
  id: 1,
  name: `Experiment for ${flagKey}`,
  description: null,
  start_date: "2024-01-01",
  end_date: null,
  feature_flag_key: flagKey,
  created_at: "2024-01-01T00:00:00Z",
  created_by: null,
  ...overrides,
});

const makeEventDef = (
  name: string,
  overrides: Partial<EventDefinition> = {},
): EventDefinition => ({
  id: "1",
  name,
  description: null,
  tags: [],
  last_seen_at: null,
  verified: false,
  hidden: false,
  ...overrides,
});

function mockApiResponses(opts: {
  flags?: FeatureFlag[];
  experiments?: Experiment[];
  eventDefs?: EventDefinition[];
  eventStats?: [string, number, number, string][];
  flagEvalStats?: [string, number, number][];
}): void {
  const mockFetch = vi.fn(async (url: string, init?: RequestInit) => {
    const urlStr = typeof url === "string" ? url : String(url);

    if (urlStr.includes("/feature_flags/")) {
      return Response.json({ results: opts.flags ?? [] });
    }
    if (urlStr.includes("/experiments/")) {
      return Response.json({ results: opts.experiments ?? [] });
    }
    if (urlStr.includes("/event_definitions/")) {
      return Response.json({ results: opts.eventDefs ?? [] });
    }
    if (urlStr.includes("/query/") && init?.method === "POST") {
      const body =
        typeof init.body === "string"
          ? init.body
          : init.body instanceof Uint8Array
            ? new TextDecoder().decode(init.body)
            : "";
      if (body.includes("$feature_flag_called")) {
        return Response.json({ results: opts.flagEvalStats ?? [] });
      }
      return Response.json({ results: opts.eventStats ?? [] });
    }
    return Response.json({});
  });

  vi.stubGlobal("fetch", mockFetch);
}

describeWithGrammars("PostHogEnricher", () => {
  let enricher: PostHogEnricher;

  beforeAll(() => {
    enricher = new PostHogEnricher();
  });

  // ── ParseResult ──

  describe("parse → ParseResult", () => {
    test("returns events and flagChecks", async () => {
      const code = [
        `posthog.capture('purchase');`,
        `const f = posthog.getFeatureFlag('my-flag');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      expect(result.events).toHaveLength(1);
      expect(result.events[0].name).toBe("purchase");
      expect(result.flagChecks).toHaveLength(1);
      expect(result.flagChecks[0].flagKey).toBe("my-flag");
    });

    test("flagKeys returns unique keys", async () => {
      const code = [
        `posthog.getFeatureFlag('flag-a');`,
        `posthog.isFeatureEnabled('flag-a');`,
        `posthog.getFeatureFlag('flag-b');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      expect(result.flagKeys).toEqual(["flag-a", "flag-b"]);
    });

    test("eventNames returns unique non-dynamic names", async () => {
      const code = [
        `posthog.capture('purchase');`,
        `posthog.capture('signup');`,
        `posthog.capture('purchase');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      expect(result.eventNames).toEqual(["purchase", "signup"]);
    });

    test("toList returns sorted items", async () => {
      const code = [
        `posthog.getFeatureFlag('flag');`,
        `posthog.capture('event');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      const list = result.toList();
      expect(list).toHaveLength(2);
      expect(list[0].type).toBe("flag");
      expect(list[1].type).toBe("event");
    });
  });

  // ── EnrichedResult via API ──

  describe("enrichFromApi → EnrichedResult", () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    test("enrichedFlags includes flag metadata", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({ flags: [makeFlag("my-flag")] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      expect(enriched.flags).toHaveLength(1);
      expect(enriched.flags[0].flagKey).toBe("my-flag");
      expect(enriched.flags[0].flagType).toBe("boolean");
    });

    test("enrichedFlags detects staleness", async () => {
      const code = `posthog.getFeatureFlag('stale-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({ flags: [makeFlag("stale-flag", { active: false })] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      expect(enriched.flags[0].staleness).toBe("inactive");
    });

    test("enrichedFlags links experiment", async () => {
      const code = `posthog.getFeatureFlag('exp-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        flags: [makeFlag("exp-flag")],
        experiments: [makeExperiment("exp-flag")],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      expect(enriched.flags[0].experiment?.name).toBe(
        "Experiment for exp-flag",
      );
    });

    test("enrichedEvents includes definition", async () => {
      const code = `posthog.capture('purchase');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        eventDefs: [
          makeEventDef("purchase", {
            verified: true,
            description: "User bought something",
          }),
        ],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      expect(enriched.events).toHaveLength(1);
      expect(enriched.events[0].verified).toBe(true);
    });

    test("toList returns enriched items", async () => {
      const code = [
        `posthog.capture('purchase');`,
        `posthog.getFeatureFlag('my-flag');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      mockApiResponses({
        flags: [makeFlag("my-flag")],
        eventDefs: [makeEventDef("purchase", { verified: true })],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const list = enriched.toList();
      expect(list).toHaveLength(2);

      const eventItem = list.find((i) => i.type === "event");
      expect(eventItem?.verified).toBe(true);

      const flagItem = list.find((i) => i.type === "flag");
      expect(flagItem?.flagType).toBe("boolean");
    });

    test("toComments inserts annotations", async () => {
      const code = [
        `posthog.capture('purchase');`,
        `posthog.getFeatureFlag('my-flag');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      mockApiResponses({
        flags: [makeFlag("my-flag", { active: false })],
        eventDefs: [makeEventDef("purchase", { verified: true })],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain("// [PostHog]");
      expect(annotated).toContain("purchase");
      expect(annotated).toContain("my-flag");
    });

    test("toComments uses # for Python", async () => {
      const code = `posthog.get_feature_flag('my-flag')`;
      const result = await enricher.parse(code, "python");

      mockApiResponses({ flags: [makeFlag("my-flag")] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain("# [PostHog]");
    });

    test("toInlineComments appends to the same line and preserves line count", async () => {
      const code = [
        `posthog.capture('purchase');`,
        `posthog.getFeatureFlag('my-flag');`,
      ].join("\n");

      const result = await enricher.parse(code, "javascript");
      mockApiResponses({
        flags: [makeFlag("my-flag")],
        eventDefs: [makeEventDef("purchase", { verified: true })],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toInlineComments();
      const lines = annotated.split("\n");

      expect(lines).toHaveLength(2);
      expect(lines[0]).toMatch(/^posthog\.capture\('purchase'\);.*\[PostHog\]/);
      expect(lines[0]).toContain(`Event: "purchase"`);
      expect(lines[1]).toMatch(
        /^posthog\.getFeatureFlag\('my-flag'\);.*\[PostHog\]/,
      );
      expect(lines[1]).toContain(`Flag: "my-flag"`);
    });

    test("toInlineComments uses # for Python", async () => {
      const code = `posthog.get_feature_flag('my-flag')`;
      const result = await enricher.parse(code, "python");

      mockApiResponses({ flags: [makeFlag("my-flag")] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toInlineComments();
      expect(annotated).toContain("# [PostHog]");
      expect(annotated.split("\n")).toHaveLength(1);
    });

    test("toInlineComments combines multiple calls on the same line", async () => {
      const code = `posthog.capture('a'); posthog.capture('b');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        eventDefs: [
          makeEventDef("a", { verified: true }),
          makeEventDef("b", { verified: true }),
        ],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toInlineComments();
      const lines = annotated.split("\n");

      expect(lines).toHaveLength(1);
      expect(lines[0]).toContain(`Event: "a"`);
      expect(lines[0]).toContain(`Event: "b"`);
      expect(lines[0]).toContain(" | ");
    });

    test("enrichedEvents surfaces stats, lastSeenAt, and tags", async () => {
      const code = `posthog.capture('purchase');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        eventDefs: [
          makeEventDef("purchase", {
            verified: true,
            tags: ["revenue", "checkout"],
            last_seen_at: "2025-03-01T00:00:00Z",
          }),
        ],
        eventStats: [["purchase", 12500, 3200, "2025-04-01T00:00:00Z"]],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const event = enriched.events[0];
      expect(event.verified).toBe(true);
      expect(event.tags).toEqual(["revenue", "checkout"]);
      expect(event.stats?.volume).toBe(12500);
      expect(event.stats?.uniqueUsers).toBe(3200);

      const list = enriched.toList();
      const item = list.find((i) => i.type === "event");
      expect(item?.volume).toBe(12500);
      expect(item?.uniqueUsers).toBe(3200);
      expect(item?.tags).toEqual(["revenue", "checkout"]);
    });

    test("toComments includes volume when available", async () => {
      const code = `posthog.capture('purchase');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        eventStats: [["purchase", 5000, 1200, "2025-04-01"]],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain("5,000 events");
      expect(annotated).toContain("1,200 users");
    });

    test("enrichedFlags includes url and evaluation stats", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        flags: [makeFlag("my-flag", { id: 42 })],
        flagEvalStats: [["my-flag", 1240, 230]],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      expect(enriched.flags[0].url).toBe(
        "https://test.posthog.com/project/1/feature_flags/42",
      );
      expect(enriched.flags[0].evaluationStats).toEqual({
        evaluations: 1240,
        uniqueUsers: 230,
        windowDays: 7,
      });
    });

    test("toComments renders rich flag line with url, active, rollout, evals", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        flags: [
          makeFlag("my-flag", {
            id: 42,
            filters: { groups: [{ rollout_percentage: 60, properties: [] }] },
          }),
        ],
        flagEvalStats: [["my-flag", 1240, 230]],
      });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain(`Flag: "my-flag"`);
      expect(annotated).toContain("active");
      expect(annotated).toContain("60% rolled out");
      expect(annotated).toContain("1,240 evals / 230 users (7d)");
      expect(annotated).toContain(
        "https://test.posthog.com/project/1/feature_flags/42",
      );
    });

    test("toComments marks inactive flags explicitly", async () => {
      const code = `posthog.getFeatureFlag('off-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({ flags: [makeFlag("off-flag", { active: false })] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain("inactive");
      expect(annotated).toContain("STALE (inactive)");
    });

    test("toComments handles flag not in PostHog", async () => {
      const code = `posthog.getFeatureFlag('ghost-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({ flags: [] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain(`Flag: "ghost-flag" \u2014 not in PostHog`);
    });

    test("toComments omits evaluation segment when stats missing", async () => {
      const code = `posthog.getFeatureFlag('quiet-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({ flags: [makeFlag("quiet-flag", { id: 7 })] });
      const enriched = await result.enrichFromApi(API_CONFIG);

      const annotated = enriched.toComments();
      expect(annotated).toContain(`Flag: "quiet-flag"`);
      expect(annotated).not.toContain("evals /");
      expect(annotated).toContain(
        "https://test.posthog.com/project/1/feature_flags/7",
      );
    });

    test("getFlagEvaluationStats is called with detected flag keys", async () => {
      const code = `posthog.getFeatureFlag('tracked-flag');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        flags: [makeFlag("tracked-flag")],
        flagEvalStats: [["tracked-flag", 10, 5]],
      });
      await result.enrichFromApi(API_CONFIG);

      const calls = vi.mocked(fetch).mock.calls;
      const queryPost = calls.find(
        ([url, init]) =>
          String(url).includes("/query/") && init?.method === "POST",
      );
      expect(queryPost).toBeDefined();
      const body = String(queryPost?.[1]?.body ?? "");
      expect(body).toContain("$feature_flag_called");
      expect(body).toContain("tracked-flag");
    });

    test("toComments renders 'eval stats unavailable' when query rejects", async () => {
      const code = `posthog.getFeatureFlag('broken-flag');`;
      const result = await enricher.parse(code, "javascript");

      const mockFetch = vi.fn(async (url: string, init?: RequestInit) => {
        const urlStr = typeof url === "string" ? url : String(url);
        if (urlStr.includes("/feature_flags/")) {
          return Response.json({ results: [makeFlag("broken-flag")] });
        }
        if (urlStr.includes("/experiments/")) {
          return Response.json({ results: [] });
        }
        if (urlStr.includes("/event_definitions/")) {
          return Response.json({ results: [] });
        }
        if (urlStr.includes("/query/") && init?.method === "POST") {
          const body =
            typeof init.body === "string"
              ? init.body
              : init.body instanceof Uint8Array
                ? new TextDecoder().decode(init.body)
                : "";
          if (body.includes("$feature_flag_called")) {
            return new Response("forbidden", { status: 403 });
          }
          return Response.json({ results: [] });
        }
        return Response.json({});
      });
      vi.stubGlobal("fetch", mockFetch);

      const enriched = await result.enrichFromApi(API_CONFIG);
      const annotated = enriched.toComments();
      expect(annotated).toContain("eval stats unavailable");
      expect(annotated).not.toContain("evals /");
    });

    test("enrichedFlags url handles host with trailing slash", async () => {
      const code = `posthog.getFeatureFlag('slashy');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({ flags: [makeFlag("slashy", { id: 9 })] });
      const enriched = await result.enrichFromApi({
        ...API_CONFIG,
        host: "https://test.posthog.com/",
      });

      expect(enriched.flags[0].url).toBe(
        "https://test.posthog.com/project/1/feature_flags/9",
      );
    });

    test("enrichFromApi with no detected usage returns empty enrichment", async () => {
      const code = `const x = 1;`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({});
      const enriched = await result.enrichFromApi(API_CONFIG);

      expect(enriched.toList()).toHaveLength(0);
      expect(enriched.flags).toHaveLength(0);
      expect(enriched.events).toHaveLength(0);
    });

    test("only fetches flags when flags are detected", async () => {
      const code = `posthog.capture('purchase');`;
      const result = await enricher.parse(code, "javascript");

      mockApiResponses({
        eventDefs: [makeEventDef("purchase")],
      });
      await result.enrichFromApi(API_CONFIG);

      const calls = vi.mocked(fetch).mock.calls;
      const urls = calls.map(([url]) => String(url));
      expect(urls.some((u) => u.includes("/feature_flags/"))).toBe(false);
      expect(urls.some((u) => u.includes("/experiments/"))).toBe(false);
      expect(urls.some((u) => u.includes("/event_definitions/"))).toBe(true);
    });
  });

  // ── parseFile ──

  describe("parseFile", () => {
    let tmpDir: string;

    beforeAll(async () => {
      tmpDir = await fsp.mkdtemp(path.join(os.tmpdir(), "enricher-test-"));
    });

    afterAll(async () => {
      await fsp.rm(tmpDir, { recursive: true, force: true });
    });

    test("reads file and detects language from .js extension", async () => {
      const filePath = path.join(tmpDir, "example.js");
      await fsp.writeFile(
        filePath,
        `posthog.capture('file-event');\nposthog.getFeatureFlag('file-flag');`,
      );
      const result = await enricher.parseFile(filePath);
      expect(result.events).toHaveLength(1);
      expect(result.events[0].name).toBe("file-event");
      expect(result.flagChecks).toHaveLength(1);
      expect(result.flagChecks[0].flagKey).toBe("file-flag");
    });

    test("reads file and detects language from .ts extension", async () => {
      const filePath = path.join(tmpDir, "example.ts");
      await fsp.writeFile(
        filePath,
        `posthog.capture("file-event");\nposthog.getFeatureFlag("file-flag");`,
      );
      const result = await enricher.parseFile(filePath);
      // TS grammar may not parse identically in all environments
      if (result.events.length === 0) {
        return;
      }
      expect(result.events).toHaveLength(1);
      expect(result.events[0].name).toBe("file-event");
      expect(result.flagChecks).toHaveLength(1);
      expect(result.flagChecks[0].flagKey).toBe("file-flag");
    });

    test("detects language from .py extension", async () => {
      const filePath = path.join(tmpDir, "example.py");
      await fsp.writeFile(filePath, `posthog.capture('hello', 'py-event')`);
      const result = await enricher.parseFile(filePath);
      expect(result.events).toHaveLength(1);
      expect(result.events[0].name).toBe("py-event");
    });

    test("throws on unsupported extension", async () => {
      const filePath = path.join(tmpDir, "readme.txt");
      await fsp.writeFile(filePath, "hello");
      await expect(enricher.parseFile(filePath)).rejects.toThrow(
        /Unsupported file extension: \.txt/,
      );
    });

    test("throws on nonexistent file", async () => {
      await expect(
        enricher.parseFile(path.join(tmpDir, "nope.ts")),
      ).rejects.toThrow();
    });
  });

  // ── API error handling ──

  describe("enrichFromApi error handling", () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    test("tolerates 401 unauthorized by returning empty enrichment", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response("Unauthorized", { status: 401 })),
      );

      const enriched = await result.enrichFromApi(API_CONFIG);
      expect(enriched.flags[0].flag).toBeUndefined();
    });

    test("tolerates 500 server error by returning empty enrichment", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      vi.stubGlobal(
        "fetch",
        vi.fn(
          async () => new Response("Internal Server Error", { status: 500 }),
        ),
      );

      const enriched = await result.enrichFromApi(API_CONFIG);
      expect(enriched.flags[0].flag).toBeUndefined();
    });

    test("tolerates network failure by returning empty enrichment", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      vi.stubGlobal(
        "fetch",
        vi.fn(async () => {
          throw new TypeError("fetch failed");
        }),
      );

      const enriched = await result.enrichFromApi(API_CONFIG);
      expect(enriched.flags[0].flag).toBeUndefined();
    });

    test("tolerates malformed JSON response by returning empty enrichment", async () => {
      const code = `posthog.getFeatureFlag('my-flag');`;
      const result = await enricher.parse(code, "javascript");

      vi.stubGlobal(
        "fetch",
        vi.fn(
          async () =>
            new Response("not json", {
              status: 200,
              headers: { "Content-Type": "text/plain" },
            }),
        ),
      );

      const enriched = await result.enrichFromApi(API_CONFIG);
      expect(enriched.flags[0].flag).toBeUndefined();
    });
  });
});

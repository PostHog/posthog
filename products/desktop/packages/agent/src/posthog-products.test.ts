import { describe, expect, it } from "vitest";
import {
  classifyPostHogExecCall,
  classifyPostHogSqlQuery,
  classifyPostHogSubTool,
  isUnclassifiedPostHogSubTool,
  POSTHOG_PRODUCTS,
  type PostHogProductId,
} from "./posthog-products";

describe("classifyPostHogSubTool", () => {
  it.each([
    ["experiment-list", "experiments"],
    ["feature-flag-update", "feature_flags"],
    ["early-access-feature-create", "feature_flags"],
    ["error-tracking-issue-update", "error_tracking"],
    ["session-recording-get", "session_replay"],
    ["survey-create", "surveys"],
    ["execute-sql", "sql"],
    ["external-data-sources-list", "data_warehouse"],
    ["cdp-functions-list", "cdp"],
    ["insight-create", "product_analytics"],
  ])("maps resource sub-tool %s to %s", (subTool, product) => {
    expect(classifyPostHogSubTool(subTool)).toBe(product);
  });

  // Domains that previously fell through to the generic fallback — keyed on a
  // longer per-sub-tool name than the canonical token, or missing entirely.
  it.each([
    ["llma-evaluation-list", "llm_analytics"],
    ["llma-clustering-get", "llm_analytics"],
    ["llma-trace-get", "llm_analytics"],
    ["notebook-create", "product_analytics"],
    ["cdp-function-update", "cdp"],
    ["cdp-function-templates-list", "cdp"],
    ["external-data-schemas-list", "data_warehouse"],
    ["event-definition-list", "product_analytics"],
    ["custom-property-definitions-list", "product_analytics"],
    ["web-analytics-weekly-digest-get", "web_analytics"],
    ["vision-scanners-create", "session_replay"],
  ])("maps newly-covered sub-tool %s to %s", (subTool, product) => {
    expect(classifyPostHogSubTool(subTool)).toBe(product);
  });

  it.each([
    ["query-trends", "product_analytics"],
    ["query-trends-actors", "product_analytics"],
    ["query-paths", "product_analytics"],
    ["query-error-tracking-issues-list", "error_tracking"],
    ["query-session-recordings-list", "session_replay"],
    ["query-llm-traces-list", "llm_analytics"],
    ["query-logs", "logs"],
    ["query-apm-spans", "apm"],
  ])("classifies query sub-tool %s as %s", (subTool, product) => {
    expect(classifyPostHogSubTool(subTool)).toBe(product);
  });

  // `llm` must not swallow the distinct `llma-*` domains.
  it.each([
    ["llm-costs", "llm_analytics"],
    ["llma-personal-spend", "llm_analytics"],
  ])(
    "does not let a short domain shadow a longer one: %s",
    (subTool, product) => {
      expect(classifyPostHogSubTool(subTool)).toBe(product);
    },
  );

  // Plural and verb-first tool names resolve to the same domain product as the
  // canonical singular form — no per-variant entry required.
  it.each([
    ["feature-flags-activity-retrieve", "feature_flags"],
    ["feature-flags-status-retrieve", "feature_flags"],
    ["create-feature-flag", "feature_flags"],
    ["update-feature-flag", "feature_flags"],
    ["delete-feature-flag", "feature_flags"],
    // The fix is general, not flag-specific.
    ["create-survey", "surveys"],
    ["create-experiment", "experiments"],
  ])("matches plural/verb-first variant %s to %s", (subTool, product) => {
    expect(classifyPostHogSubTool(subTool)).toBe(product);
  });

  it.each(["project-get", "activity-log-list", "docs-search", "tasks-list"])(
    "returns null for admin/meta/introspection domain %s",
    (subTool) => {
      expect(classifyPostHogSubTool(subTool)).toBeNull();
    },
  );

  it("returns null for unrecognized domains rather than a generic chip", () => {
    expect(classifyPostHogSubTool("brand-new-thing-list")).toBeNull();
  });

  it.each(["", "   "])("returns null for empty input %j", (subTool) => {
    expect(classifyPostHogSubTool(subTool)).toBeNull();
  });

  it("only emits ids that exist in POSTHOG_PRODUCTS", () => {
    const ids = [
      "experiment-list",
      "query-trends",
      "execute-sql",
      "brand-new-thing-list",
    ]
      .map(classifyPostHogSubTool)
      .filter((id): id is NonNullable<typeof id> => id !== null);
    for (const id of ids) {
      expect(POSTHOG_PRODUCTS[id]).toBeDefined();
    }
  });
});

describe("isUnclassifiedPostHogSubTool", () => {
  it.each(["brand-new-thing-list", "totally-made-up-get"])(
    "flags genuinely-unknown domain %s",
    (subTool) => {
      expect(isUnclassifiedPostHogSubTool(subTool)).toBe(true);
    },
  );

  it.each([
    // Mapped product domains.
    "experiment-list",
    "llma-evaluation-list",
    "vision-scanners-create",
    "custom-property-definitions-list",
    // Deliberately-suppressed admin/meta domains — recognized, not unknown.
    "project-get",
    "docs-search",
    "tasks-list",
    // Special-cased call shapes.
    "query-trends",
    "execute-sql",
    "activity-log-list",
    // Empty input.
    "",
    "   ",
  ])("does not flag recognized or special-cased call %j", (subTool) => {
    expect(isUnclassifiedPostHogSubTool(subTool)).toBe(false);
  });
});

describe("classifyPostHogSqlQuery", () => {
  it.each([
    ["SELECT count() FROM feature_flags", ["feature_flags"]],
    ["select * from experiments", ["experiments"]],
    ["SELECT * FROM events LIMIT 10", ["product_analytics"]],
  ])("attributes %s to the product behind its tables", (sql, expected) => {
    expect(classifyPostHogSqlQuery(sql)).toEqual(expected);
  });

  it("resolves a schema-qualified table by its bare name", () => {
    expect(
      classifyPostHogSqlQuery("SELECT count() FROM system.feature_flags"),
    ).toEqual(["feature_flags"]);
  });

  it("handles quoted/back-ticked identifiers", () => {
    expect(classifyPostHogSqlQuery("SELECT * FROM `feature_flags`")).toEqual([
      "feature_flags",
    ]);
  });

  it("collects products across joins, deduped", () => {
    const products = classifyPostHogSqlQuery(
      "SELECT * FROM events e JOIN persons p ON e.person_id = p.id JOIN feature_flags f ON true",
    );
    expect(products).toContain("product_analytics");
    expect(products).toContain("feature_flags");
    // events + persons both map to product_analytics — deduped to one entry.
    expect(products.filter((p) => p === "product_analytics")).toHaveLength(1);
  });

  it.each(["SELECT 1", "SELECT * FROM some_warehouse_table"])(
    "returns nothing when no referenced table maps: %s",
    (sql) => {
      expect(classifyPostHogSqlQuery(sql)).toEqual([]);
    },
  );

  // Exact-name match only — a similarly-named warehouse table is left alone.
  it.each([
    "SELECT * FROM statsig_feature_flags",
    "SELECT * FROM feature_flags_archive",
  ])(
    "does not match warehouse table that merely contains a name: %s",
    (sql) => {
      expect(classifyPostHogSqlQuery(sql)).toEqual([]);
    },
  );

  // A non-PostHog schema prefix (a warehouse source) is a different table.
  it.each([
    "SELECT * FROM stripe.feature_flags",
    "SELECT * FROM my_source.events",
  ])("does not match a non-PostHog-schema-qualified table: %s", (sql) => {
    expect(classifyPostHogSqlQuery(sql)).toEqual([]);
  });
});

describe("classifyPostHogExecCall", () => {
  it("attributes execute-sql to the queried product, not generic SQL", () => {
    expect(
      classifyPostHogExecCall(
        "execute-sql",
        'call execute-sql {"query":"SELECT count() FROM feature_flags"}',
      ),
    ).toEqual(["feature_flags"]);
  });

  it("falls back to the sql product when no table maps", () => {
    expect(
      classifyPostHogExecCall(
        "execute-sql",
        'call execute-sql {"query":"SELECT 1"}',
      ),
    ).toEqual(["sql"]);
    // No command text at all → still surfaces something rather than vanishing.
    expect(classifyPostHogExecCall("execute-sql")).toEqual(["sql"]);
  });

  it("delegates non-sql sub-tools to the domain classifier", () => {
    expect(classifyPostHogExecCall("feature-flag-list")).toEqual([
      "feature_flags",
    ]);
    expect(classifyPostHogExecCall("experiment-get")).toEqual(["experiments"]);
  });

  it.each<[string, string | undefined, PostHogProductId[]]>([
    // Plural tool name resolves via the pattern matcher.
    [
      "feature-flags-activity-retrieve",
      'call feature-flags-activity-retrieve {"id":1}',
      ["feature_flags"],
    ],
    // Activity-log reads are attributed by their scope...
    [
      "activity-log-list",
      'call activity-log-list {"scope":"FeatureFlag"}',
      ["feature_flags"],
    ],
    // ...including web analytics, only reachable from the log via this scope.
    [
      "activity-log-list",
      'call activity-log-list {"scope":"WebAnalyticsFilterPreset"}',
      ["web_analytics"],
    ],
    // Multiple scopes are collected and deduped.
    [
      "advanced-activity-logs-list",
      'call advanced-activity-logs-list {"scopes":["FeatureFlag","Insight"]}',
      ["feature_flags", "product_analytics"],
    ],
  ])("attributes %s to its scope/domain product", (subTool, cmd, expected) => {
    expect(classifyPostHogExecCall(subTool, cmd)).toEqual(expected);
  });

  it.each<[string, string | undefined]>([
    // Admin/meta sub-tool.
    ["project-get", undefined],
    // Unscoped or empty-scope activity-log reads.
    ["activity-log-list", 'call activity-log-list {"page":1}'],
    [
      "advanced-activity-logs-list",
      'call advanced-activity-logs-list {"scopes":[]}',
    ],
    // Admin/meta scope is not surfaced.
    ["activity-log-list", 'call activity-log-list {"scope":"Team"}'],
    // No command text to read a scope from.
    ["activity-log-list", undefined],
  ])("returns nothing for %s", (subTool, cmd) => {
    expect(classifyPostHogExecCall(subTool, cmd)).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";
import {
  type FeedQueryPlanContext,
  type FeedQueryTask,
  lexFeedQuery,
  parseFeedQuery,
  planFeedQuery,
  suggestFeedName,
} from "./feedQuery";

const shy = {
  id: 1,
  uuid: "uuid-shy",
  email: "shy@example.com",
  first_name: "Shy",
  last_name: "Levi",
};
const moshe = {
  id: 2,
  uuid: "uuid-moshe",
  email: "moshe@example.com",
  first_name: "Moshe",
  last_name: "Katz",
};

const context: FeedQueryPlanContext = {
  members: [shy, moshe],
  spaces: [
    { id: "space-mobile", name: "mobile" },
    { id: "space-web", name: "desktop app" },
  ],
  me: shy,
  reportsEnabled: true,
};

function task(overrides: Partial<FeedQueryTask> = {}): FeedQueryTask {
  return {
    created_by: { uuid: "uuid-shy" },
    channel: "space-mobile",
    repository: "example-org/webapp",
    origin_product: "user_created",
    latest_run: { status: "completed", output: null },
    ...overrides,
  };
}

describe("feedQuery", () => {
  describe("parseFeedQuery", () => {
    it("splits filter tokens from free text", () => {
      const parsed = parseFeedQuery("fix billing created-by:shy status:failed");
      expect(parsed.text).toBe("fix billing");
      expect(parsed.tokens).toEqual([
        {
          raw: "created-by:shy",
          key: "created-by",
          value: "shy",
          negated: false,
        },
        {
          raw: "status:failed",
          key: "status",
          value: "failed",
          negated: false,
        },
      ]);
      expect(parsed.issues).toEqual([]);
    });

    it.each([
      ["-pr:merged", true],
      ["pr:not:merged", true],
      ["pr:merged", false],
    ])("reads negation in %s", (query, negated) => {
      const parsed = parseFeedQuery(query);
      expect(parsed.tokens[0]).toMatchObject({ value: "merged", negated });
    });

    it("maps aliases onto canonical keys", () => {
      const parsed = parseFeedQuery(
        "author:shy channel:mobile repository:web commenter:shy mentioned:shy",
      );
      expect(parsed.tokens.map((t) => t.key)).toEqual([
        "created-by",
        "space",
        "repo",
        "commented-by",
        "mentions",
      ]);
    });

    it("carries spaces through quoted values", () => {
      const parsed = parseFeedQuery('space:"desktop app" "exact phrase"');
      expect(parsed.tokens[0].value).toBe("desktop app");
      expect(parsed.text).toBe("exact phrase");
    });

    it("treats unknown keys as free text so URLs survive", () => {
      const parsed = parseFeedQuery("see https://example.com/x foo:bar");
      expect(parsed.tokens).toEqual([]);
      expect(parsed.text).toBe("see https://example.com/x foo:bar");
    });

    it("drops a dangling key someone is mid-typing", () => {
      const parsed = parseFeedQuery("status:");
      expect(parsed.tokens).toEqual([]);
      expect(parsed.issues).toEqual([]);
    });

    it.each([
      ["status:sideways", "unknown-value"],
      ["is:sideways", "unknown-value"],
      ["pr:sideways", "unknown-value"],
      ["ci:sideways", "unknown-value"],
      ["type:canvas", "unknown-value"],
    ])("flags %s as %s", (query, kind) => {
      const parsed = parseFeedQuery(query);
      expect(parsed.issues).toHaveLength(1);
      expect(parsed.issues[0].kind).toBe(kind);
    });
  });

  describe("lexFeedQuery", () => {
    it.each([
      "fix billing created-by:shy -status:failed",
      '  space:"desktop app"  trailing ',
      "https://example.com/x pr:not:merged",
    ])("reproduces %j exactly from its segments", (query) => {
      const segments = lexFeedQuery(query);
      expect(segments.map((segment) => segment.raw).join("")).toBe(query);

      let start = 0;
      for (const segment of segments) {
        expect(segment.start).toBe(start);
        start += segment.raw.length;
      }
    });

    it("classifies tokens, text, and mid-typing fragments", () => {
      const segments = lexFeedQuery("fix -status:failed status:");
      expect(segments.map((s) => s.kind)).toEqual([
        "text",
        "whitespace",
        "token",
        "whitespace",
        // A dangling `status:` renders as plain text to avoid a red flash mid-type.
        "text",
      ]);
      expect(segments[2].token).toMatchObject({
        key: "status",
        value: "failed",
        negated: true,
        invalid: false,
        unsupported: false,
      });
    });

    it("flags invalid values for the highlighter", () => {
      const segments = lexFeedQuery("status:sideways ci:red");
      expect(segments[0].token).toMatchObject({ invalid: true });
      expect(segments[2].token).toMatchObject({
        invalid: false,
        unsupported: false,
      });
    });
  });

  describe("planFeedQuery", () => {
    it("compiles single positive filters into one server request", () => {
      const plan = planFeedQuery(
        parseFeedQuery(
          "billing created-by:shy space:mobile repo:webapp status:failed origin:slack is:archived",
        ),
        context,
      );
      expect(plan.requests).toEqual([
        {
          search: "billing",
          createdBy: 1,
          channel: "space-mobile",
          repository: "webapp",
          status: "failed",
          originProduct: "slack",
          archived: true,
        },
      ]);
      expect(plan.matches(task())).toBe(true);
    });

    it("resolves created-by:@me through the viewer", () => {
      const plan = planFeedQuery(parseFeedQuery("created-by:@me"), context);
      expect(plan.requests).toEqual([{ createdBy: shy.id }]);
    });

    // The regression this guards: with the OR filtered client-side over one
    // unfiltered page, both authors' tasks vanished the moment they aged out
    // of the most recent page, which made two working filters produce zero rows.
    it("fans a repeated key out into one server request per value", () => {
      const plan = planFeedQuery(
        parseFeedQuery("created-by:shy created-by:moshe"),
        context,
      );
      expect(plan.requests).toEqual([
        { createdBy: shy.id },
        { createdBy: moshe.id },
      ]);
      expect(plan.matches(task({ created_by: { uuid: "uuid-shy" } }))).toBe(
        true,
      );
      expect(plan.matches(task({ created_by: { uuid: "uuid-moshe" } }))).toBe(
        true,
      );
      expect(plan.matches(task({ created_by: { uuid: "uuid-else" } }))).toBe(
        false,
      );
    });

    it("carries shared filters into every fanned-out request", () => {
      const plan = planFeedQuery(
        parseFeedQuery("created-by:shy created-by:moshe status:failed"),
        context,
      );
      expect(plan.requests).toEqual([
        { createdBy: shy.id, status: "failed" },
        { createdBy: moshe.id, status: "failed" },
      ]);
    });

    it("folds duplicate spellings of one person into one request", () => {
      const plan = planFeedQuery(
        parseFeedQuery("created-by:shy author:shy@example.com"),
        context,
      );
      expect(plan.requests).toEqual([{ createdBy: shy.id }]);
    });

    it("keeps negations out of server params and filters them client-side", () => {
      const plan = planFeedQuery(
        parseFeedQuery("-created-by:moshe -status:failed"),
        context,
      );
      expect(plan.requests).toEqual([{}]);
      expect(plan.matches(task())).toBe(true);
      expect(plan.matches(task({ created_by: { uuid: "uuid-moshe" } }))).toBe(
        false,
      );
      expect(
        plan.matches(task({ latest_run: { status: "failed", output: null } })),
      ).toBe(false);
    });

    it("folds is: sugar into the status group", () => {
      const plan = planFeedQuery(
        parseFeedQuery("is:running status:failed"),
        context,
      );
      expect(plan.requests).toEqual([
        { status: "in_progress" },
        { status: "failed" },
      ]);
      expect(
        plan.matches(
          task({ latest_run: { status: "in_progress", output: null } }),
        ),
      ).toBe(true);
      expect(
        plan.matches(task({ latest_run: { status: "failed", output: null } })),
      ).toBe(true);
      expect(
        plan.matches(
          task({ latest_run: { status: "completed", output: null } }),
        ),
      ).toBe(false);
    });

    it.each([
      ["pr:any", true, false],
      ["pr:none", false, true],
      ["-pr:none", true, false],
      ["-pr:any", false, true],
    ])("%s filters on PR presence", (query, withPr, withoutPr) => {
      const plan = planFeedQuery(parseFeedQuery(query), context);
      const prTask = task({
        latest_run: {
          status: "completed",
          output: { pr_url: "https://github.com/example-org/webapp/pull/1" },
        },
      });
      expect(plan.matches(prTask)).toBe(withPr);
      expect(plan.matches(task())).toBe(withoutPr);
    });

    it("compiles pr states and ci status into server params", () => {
      const plan = planFeedQuery(parseFeedQuery("pr:merged ci:red"), context);
      expect(plan.requests).toEqual([
        { prState: "merged", ciStatus: "failing" },
      ]);
      expect(plan.issues).toEqual([]);
    });

    it("fans repeated pr states out into one request per state", () => {
      const plan = planFeedQuery(parseFeedQuery("pr:open pr:draft"), context);
      expect(plan.requests).toEqual([
        { prState: "open" },
        { prState: "draft" },
      ]);
      const openTask = task({
        latest_run: {
          status: "completed",
          output: { pr_url: "https://github.com/x/y/pull/1", pr_state: "open" },
        },
      });
      expect(plan.matches(openTask)).toBe(true);
      expect(plan.matches(task())).toBe(false);
    });

    it("matches pr:merged on the legacy pr_merged flag client-side", () => {
      // Two values force the client predicate; a legacy run carries only
      // pr_merged, and must still count as merged.
      const plan = planFeedQuery(
        parseFeedQuery("pr:merged pr:closed"),
        context,
      );
      const legacyMerged = task({
        latest_run: {
          status: "completed",
          output: { pr_url: "https://github.com/x/y/pull/1", pr_merged: true },
        },
      });
      expect(plan.matches(legacyMerged)).toBe(true);
      expect(plan.matches(task())).toBe(false);
    });

    it("keeps pr presence values client-side", () => {
      const plan = planFeedQuery(parseFeedQuery("pr:any pr:merged"), context);
      expect(plan.requests).toEqual([{}]);
      const prTask = task({
        latest_run: {
          status: "completed",
          output: { pr_url: "https://github.com/x/y/pull/1" },
        },
      });
      expect(plan.matches(prTask)).toBe(true);
      expect(plan.matches(task())).toBe(false);
    });

    it("filters ci status client-side when negated", () => {
      const plan = planFeedQuery(parseFeedQuery("-ci:red"), context);
      expect(plan.requests).toEqual([{}]);
      const failing = task({
        latest_run: {
          status: "completed",
          output: {
            pr_url: "https://github.com/x/y/pull/1",
            ci_status: "failing",
          },
        },
      });
      expect(plan.matches(failing)).toBe(false);
      expect(plan.matches(task())).toBe(true);
    });

    it("takes no predicate from an unknown pr value", () => {
      const plan = planFeedQuery(parseFeedQuery("pr:sideways"), context);
      expect(plan.matches(task())).toBe(true);
      expect(plan.issues.map((i) => i.kind)).toEqual(["unknown-value"]);
    });

    it.each([
      ["origin:desktop", "user_created"],
      ["origin:scout", "signals_scout"],
      ["origin:ai", "posthog_ai"],
      ["origin:slack", "slack"],
      ["origin:hogdesk", "hogdesk"],
    ])("aliases %s onto the origin enum", (query, expected) => {
      const plan = planFeedQuery(parseFeedQuery(query), context);
      expect(plan.requests).toEqual([{ originProduct: expected }]);
    });

    it("aliases origins inside OR groups and negations", () => {
      const plan = planFeedQuery(
        parseFeedQuery("origin:scout origin:desktop"),
        context,
      );
      expect(plan.requests).toEqual([
        { originProduct: "signals_scout" },
        { originProduct: "user_created" },
      ]);
      expect(plan.matches(task({ origin_product: "signals_scout" }))).toBe(
        true,
      );
      expect(plan.matches(task({ origin_product: "slack" }))).toBe(false);

      const negated = planFeedQuery(parseFeedQuery("-origin:scout"), context);
      expect(negated.matches(task({ origin_product: "signals_scout" }))).toBe(
        false,
      );
      expect(negated.matches(task({ origin_product: "slack" }))).toBe(true);
    });

    it("compiles is:pinned into the pinned request param", () => {
      const plan = planFeedQuery(parseFeedQuery("is:pinned"), context);
      expect(plan.requests).toEqual([{ pinned: true }]);
    });

    it("matches no tasks when archived is both required and excluded", () => {
      const plan = planFeedQuery(
        parseFeedQuery("is:archived -is:archived"),
        context,
      );
      expect(plan.requests).toEqual([{}]);
      expect(plan.matches(task())).toBe(false);
    });

    it("flags -is:pinned as unsupported instead of silently ignoring it", () => {
      const plan = planFeedQuery(parseFeedQuery("-is:pinned"), context);
      expect(plan.requests).toEqual([{}]);
      expect(plan.issues.map((i) => i.kind)).toEqual(["unsupported"]);
    });

    it("flags -type:task as ignored instead of returning every task", () => {
      const plan = planFeedQuery(parseFeedQuery("-type:task"), context);
      expect(plan.requests).toEqual([{}]);
      expect(plan.matches(task())).toBe(true);
      expect(plan.issues.map((i) => i.kind)).toEqual(["unsupported"]);
    });

    it.each([
      ["commented-by:shy", { commentedBy: shy.id }],
      ["mentions:@me", { mentions: shy.id }],
    ])("compiles %s into a server param", (query, expected) => {
      const plan = planFeedQuery(parseFeedQuery(query), context);
      expect(plan.requests).toEqual([expected]);
      expect(plan.issues).toEqual([]);
    });

    it("fans repeated commented-by out into one request per person", () => {
      const plan = planFeedQuery(
        parseFeedQuery("commented-by:shy commented-by:moshe"),
        context,
      );
      expect(plan.requests).toEqual([
        { commentedBy: shy.id },
        { commentedBy: moshe.id },
      ]);
    });

    it("spells involves as one request per leg", () => {
      const plan = planFeedQuery(parseFeedQuery("involves:shy"), context);
      expect(plan.requests).toEqual([
        { createdBy: shy.id },
        { commentedBy: shy.id },
      ]);
    });

    it("reports involves combined with created-by instead of widening", () => {
      const plan = planFeedQuery(
        parseFeedQuery("created-by:moshe involves:shy"),
        context,
      );
      expect(plan.requests).toEqual([{ createdBy: moshe.id }]);
      expect(plan.issues.map((i) => i.kind)).toEqual(["unsupported"]);
    });

    it("flags a negated comment filter instead of silently ignoring it", () => {
      const plan = planFeedQuery(parseFeedQuery("-commented-by:shy"), context);
      expect(plan.requests).toEqual([{}]);
      expect(plan.matches(task())).toBe(true);
      expect(plan.issues.map((i) => i.kind)).toEqual(["unsupported"]);
    });

    it("matches nothing when a comment filter names nobody", () => {
      const plan = planFeedQuery(
        parseFeedQuery("commented-by:nobody"),
        context,
      );
      expect(plan.matches(task())).toBe(false);
      expect(plan.issues.some((i) => i.message.includes("nobody"))).toBe(true);
    });

    it("reports an unresolved teammate and matches nothing", () => {
      const plan = planFeedQuery(parseFeedQuery("created-by:nobody"), context);
      expect(plan.issues.some((i) => i.message.includes("nobody"))).toBe(true);
      expect(plan.matches(task())).toBe(false);
    });

    it("reports an unknown space name", () => {
      const plan = planFeedQuery(parseFeedQuery("space:missing"), context);
      expect(plan.requests).toEqual([{}]);
      expect(plan.issues.some((i) => i.message.includes("missing"))).toBe(true);
    });

    it("stays in tasks mode without type:report", () => {
      const plan = planFeedQuery(parseFeedQuery("space:mobile"), context);
      expect(plan.mode).toBe("tasks");
      expect(plan.matchesReport).toBeUndefined();
    });
  });

  describe("planFeedQuery type:report", () => {
    it("flips the plan into reports mode with no task requests", () => {
      const plan = planFeedQuery(parseFeedQuery("type:report"), context);
      expect(plan.mode).toBe("reports");
      expect(plan.requests).toEqual([]);
      expect(plan.reportChannelId).toBeUndefined();
    });

    it("ignores type:report when the reports rollout is off", () => {
      const plan = planFeedQuery(parseFeedQuery("type:report"), {
        ...context,
        reportsEnabled: false,
      });
      // Stays a task feed and flags the token instead of opening the unreleased
      // reports-only mode.
      expect(plan.mode).toBe("tasks");
      expect(plan.matchesReport).toBeUndefined();
      expect(
        plan.issues.some(
          (i) => i.kind === "unsupported" && i.raw === "type:report",
        ),
      ).toBe(true);
    });

    it("space: narrows the report fetch to that space", () => {
      const plan = planFeedQuery(
        parseFeedQuery("type:report space:mobile"),
        context,
      );
      expect(plan.mode).toBe("reports");
      expect(plan.reportChannelId).toBe("space-mobile");
    });

    it("an unknown space narrows to nothing instead of every report", () => {
      const plan = planFeedQuery(
        parseFeedQuery("type:report space:missing"),
        context,
      );
      expect(plan.mode).toBe("reports");
      expect(plan.reportChannelId).toBeUndefined();
      expect(plan.issues.some((i) => i.message.includes("missing"))).toBe(true);
      // Without a resolved channel filter the fetch is unscoped, so the plan
      // must reject every report client-side rather than show the whole team's.
      expect(plan.matchesReport?.({ title: "Any", status: "ready" })).toBe(
        false,
      );
    });

    it("flags task-shaped tokens as unsupported instead of half-applying them", () => {
      const plan = planFeedQuery(
        parseFeedQuery("type:report status:failed created-by:shy"),
        context,
      );
      expect(plan.mode).toBe("reports");
      expect(
        plan.issues.filter((i) => i.kind === "unsupported").map((i) => i.raw),
      ).toEqual(expect.arrayContaining(["status:failed", "created-by:shy"]));
    });

    it("free text matches report titles case-insensitively", () => {
      const plan = planFeedQuery(
        parseFeedQuery("type:report billing"),
        context,
      );
      const matches = plan.matchesReport;
      expect(matches?.({ title: "Fix Billing bug", status: "ready" })).toBe(
        true,
      );
      expect(matches?.({ title: "Cohort query", status: "ready" })).toBe(false);
    });

    it.each(["suppressed", "resolved", "deleted"])(
      "excludes %s reports",
      (status) => {
        const plan = planFeedQuery(parseFeedQuery("type:report"), context);
        expect(plan.matchesReport?.({ title: "Any", status })).toBe(false);
      },
    );
  });

  describe("suggestFeedName", () => {
    it.each([
      ["created-by:@me pr:any", "My tasks with a PR"],
      ["created-by:shy created-by:adam", "Shy & Adam's tasks"],
      ["billing status:failed", "Failed billing tasks"],
      ["is:archived space:mobile", "Archived tasks in mobile"],
      ["repo:webapp pr:none", "Tasks in webapp without a PR"],
      ["is:running is:failed", "Running or failed tasks"],
      ["billing", "Billing tasks"],
      ["is:pinned", "Pinned tasks"],
      ["mentions:@me", "Tasks mentioning me"],
      ["involves:shy status:failed", "Failed tasks involving Shy"],
      ["commented-by:adam", "Tasks commented on by Adam"],
      ["", ""],
    ])("suggests a name for %j", (query, expected) => {
      expect(suggestFeedName(query)).toBe(expected);
    });
  });
});

import { describe, expect, it } from "vitest";
import {
  type FeedQueryPlanContext,
  type FeedQueryTask,
  lexFeedQuery,
  parseFeedQuery,
  planFeedQuery,
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
      const parsed = parseFeedQuery("author:shy channel:mobile repository:web");
      expect(parsed.tokens.map((t) => t.key)).toEqual([
        "created-by",
        "space",
        "repo",
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
      ["pr:merged", "unsupported"],
      ["ci:red", "unsupported"],
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
      expect(
        lexFeedQuery(query)
          .map((s) => s.raw)
          .join(""),
      ).toBe(query);
    });

    it("classifies tokens, text, and mid-typing fragments", () => {
      const segments = lexFeedQuery("fix -status:failed status:");
      expect(segments.map((s) => s.kind)).toEqual([
        "text",
        "whitespace",
        "token",
        "whitespace",
        // A dangling `status:` renders as plain text — no red flash mid-type.
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

    it("flags invalid and unsupported values for the highlighter", () => {
      const segments = lexFeedQuery("status:sideways ci:red");
      expect(segments[0].token).toMatchObject({ invalid: true });
      expect(segments[2].token).toMatchObject({
        invalid: false,
        unsupported: true,
      });
    });
  });

  describe("planFeedQuery", () => {
    it("compiles single positive filters into server params", () => {
      const plan = planFeedQuery(
        parseFeedQuery(
          "billing created-by:shy space:mobile repo:webapp status:failed origin:slack is:archived",
        ),
        context,
      );
      expect(plan.server).toEqual({
        search: "billing",
        createdBy: 1,
        channel: "space-mobile",
        repository: "webapp",
        status: "failed",
        originProduct: "slack",
        archived: true,
      });
      expect(plan.matches(task())).toBe(true);
    });

    it("resolves created-by:@me through the viewer", () => {
      const plan = planFeedQuery(parseFeedQuery("created-by:@me"), context);
      expect(plan.server.createdBy).toBe(shy.id);
    });

    it("turns a repeated key into an OR predicate instead of a server param", () => {
      const plan = planFeedQuery(
        parseFeedQuery("created-by:shy created-by:moshe"),
        context,
      );
      expect(plan.server.createdBy).toBeUndefined();
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

    it("keeps negations out of server params and filters them client-side", () => {
      const plan = planFeedQuery(
        parseFeedQuery("-created-by:moshe -status:failed"),
        context,
      );
      expect(plan.server).toEqual({});
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
      expect(plan.server.status).toBeUndefined();
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

    it("ignores unsupported pr/ci values instead of matching nothing", () => {
      const plan = planFeedQuery(parseFeedQuery("pr:merged ci:red"), context);
      expect(plan.matches(task())).toBe(true);
      expect(plan.issues.map((i) => i.kind)).toEqual([
        "unsupported",
        "unsupported",
      ]);
    });

    it("reports an unresolved teammate and matches nothing", () => {
      const plan = planFeedQuery(parseFeedQuery("created-by:nobody"), context);
      expect(plan.issues.some((i) => i.message.includes("nobody"))).toBe(true);
      expect(plan.matches(task())).toBe(false);
    });

    it("reports an unknown space name", () => {
      const plan = planFeedQuery(parseFeedQuery("space:missing"), context);
      expect(plan.server.channel).toBeUndefined();
      expect(plan.issues.some((i) => i.message.includes("missing"))).toBe(true);
    });
  });
});

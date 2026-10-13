import { describe, expect, it } from "vitest";
import { type FeedQueryCanvas, planCanvasQuery } from "./canvasQuery";
import { type FeedQueryPlanContext, parseFeedQuery } from "./feedQuery";

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
  reportsEnabled: false,
};

describe("planCanvasQuery", () => {
  const canvases: Record<string, FeedQueryCanvas> = {
    shyMobile: {
      name: "Billing overview",
      channelId: "space-mobile",
      createdByUuid: "uuid-shy",
    },
    mosheWeb: {
      name: "Signup funnel",
      description: "Weekly billing health",
      channelId: "space-web",
      createdByUuid: "uuid-moshe",
      pinnedAt: 1,
    },
    unowned: { name: "Scratch", channelId: "space-mobile" },
  };

  it.each([
    ["type:canvas", ["shyMobile", "mosheWeb", "unowned"]],
    ["type:canvas created-by:moshe", ["mosheWeb"]],
    ["type:canvas created-by:@me", ["shyMobile"]],
    ["type:canvas created-by:shy created-by:moshe", ["shyMobile", "mosheWeb"]],
    ["type:canvas -created-by:shy", ["mosheWeb", "unowned"]],
    ["type:canvas created-by:nobody", []],
    ['type:canvas space:"desktop app"', ["mosheWeb"]],
    ["type:canvas -space:mobile", ["mosheWeb"]],
    ["type:canvas space:missing", []],
    ["type:canvas is:pinned", ["mosheWeb"]],
    ["type:canvas -is:pinned", ["shyMobile", "unowned"]],
    ["type:canvas billing", ["shyMobile", "mosheWeb"]],
    ["type:canvas created-by:shy billing", ["shyMobile"]],
  ])("%s matches %j", (query, expected) => {
    const plan = planCanvasQuery(parseFeedQuery(query), context);
    const matched = Object.entries(canvases)
      .filter(([, canvas]) => plan.matches(canvas))
      .map(([name]) => name);
    expect(matched).toEqual(expected);
  });

  it("flags task-shaped tokens as unsupported instead of half-applying them", () => {
    const plan = planCanvasQuery(
      parseFeedQuery("type:canvas status:failed repo:webapp type:task"),
      context,
    );
    expect(
      plan.issues.filter((i) => i.kind === "unsupported").map((i) => i.raw),
    ).toEqual(["type:task", "status:failed", "repo:webapp"]);
    expect(plan.matches(canvases.shyMobile)).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import {
  pickNextThinkingActivity,
  pickThinkingActivity,
  THINKING_ACTIVITIES,
} from "./thinkingActivities";

describe("thinking activities", () => {
  it("selects from a bounded random value", () => {
    expect(pickThinkingActivity(0)).toBe("Booping");
    expect(pickThinkingActivity(1)).toBe(THINKING_ACTIVITIES.at(-1));
  });

  it("always advances when the random pick matches the current activity", () => {
    expect(pickNextThinkingActivity("Booping", 0)).toBe("Crunching");
  });
});

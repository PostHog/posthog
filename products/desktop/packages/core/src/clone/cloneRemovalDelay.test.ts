import { describe, expect, it } from "vitest";
import { removalDelayMsForStatus } from "./cloneRemovalDelay";

describe("removalDelayMsForStatus", () => {
  it("removes a completed clone after 3000ms", () => {
    expect(removalDelayMsForStatus("complete")).toBe(3000);
  });

  it("removes an errored clone after 5000ms", () => {
    expect(removalDelayMsForStatus("error")).toBe(5000);
  });

  it("never removes a clone that is still cloning", () => {
    expect(removalDelayMsForStatus("cloning")).toBeNull();
  });
});

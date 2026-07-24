import { describe, expect, it, vi } from "vitest";
import {
  getRandomThinkingActivity,
  getRandomThinkingMessage,
  THINKING_MESSAGES,
} from "./thinkingMessages";

describe("thinkingMessages", () => {
  it("includes the whimsical cloud-run loading messages from desktop", () => {
    expect(THINKING_MESSAGES).toContain("Kerfuffling");
    expect(THINKING_MESSAGES).toContain("Flibbertigibbeting");
    expect(THINKING_MESSAGES).toContain("Discombobulating");
  });

  it("returns a bare activity label and a message variant with ellipsis", () => {
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0);

    expect(getRandomThinkingActivity()).toBe("Booping");
    expect(getRandomThinkingMessage()).toBe("Booping...");

    randomSpy.mockRestore();
  });
});

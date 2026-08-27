import { describe, expect, it } from "vitest";
import { assertHostCapabilities } from "./hostCapabilities";

const TOKEN_A = Symbol.for("posthog.test.capabilityA");
const TOKEN_B = Symbol.for("posthog.test.capabilityB");

function containerBinding(bound: symbol[]): {
  isBound: (t: symbol) => boolean;
} {
  const set = new Set(bound);
  return { isBound: (t) => set.has(t) };
}

describe("assertHostCapabilities", () => {
  it("passes when every required token is bound", () => {
    const container = containerBinding([TOKEN_A, TOKEN_B]);
    expect(() =>
      assertHostCapabilities(container, [
        { token: TOKEN_A, description: "A" },
        { token: TOKEN_B, description: "B" },
      ]),
    ).not.toThrow();
  });

  it("passes when there are no requirements", () => {
    expect(() =>
      assertHostCapabilities(containerBinding([]), []),
    ).not.toThrow();
  });

  it("throws listing every missing token and its description", () => {
    const container = containerBinding([TOKEN_A]);
    expect(() =>
      assertHostCapabilities(container, [
        { token: TOKEN_A, description: "A is fine" },
        { token: TOKEN_B, description: "B drives cloud runs" },
      ]),
    ).toThrowError(/missing 1 required capability/);
  });

  it("reports all missing tokens at once, not just the first", () => {
    const container = containerBinding([]);
    let message = "";
    try {
      assertHostCapabilities(container, [
        { token: TOKEN_A, description: "A drives X" },
        { token: TOKEN_B, description: "B drives Y" },
      ]);
    } catch (error) {
      message = (error as Error).message;
    }
    expect(message).toContain("missing 2 required capability");
    expect(message).toContain("A drives X");
    expect(message).toContain("B drives Y");
    expect(message).toContain(String(TOKEN_A));
    expect(message).toContain(String(TOKEN_B));
  });
});

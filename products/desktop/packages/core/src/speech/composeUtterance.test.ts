import { describe, expect, it } from "vitest";
import { composeUtterance, firstNameFromLabel } from "./composeUtterance";

describe("firstNameFromLabel", () => {
  it.each([
    { label: "Jon McCallum", expected: "Jon" },
    { label: "  Jon  ", expected: "Jon" },
    { label: "jonathon@posthog.com", expected: undefined },
    { label: "", expected: undefined },
    { label: undefined, expected: undefined },
  ])("extracts $expected from $label", ({ label, expected }) => {
    expect(firstNameFromLabel(label)).toBe(expected);
  });
});

describe("composeUtterance", () => {
  it("prefixes the task name", () => {
    expect(
      composeUtterance({ text: "moving on to search", taskTitle: "fix login" }),
    ).toBe("PostHog task 'fix login' — moving on to search");
  });

  it("addresses the user by name for agent needs-user lines", () => {
    expect(
      composeUtterance({
        text: "I need your call on which branch",
        taskTitle: "search index",
        needsUser: true,
        addressByName: true,
        firstName: "Jon",
      }),
    ).toBe(
      "PostHog task 'search index' — Hey Jon, I need your call on which branch",
    );
  });

  it("omits the greeting on the deterministic backstop (no addressByName)", () => {
    expect(
      composeUtterance({
        text: "needs your input",
        taskTitle: "deploy",
        needsUser: true,
        firstName: "Jon",
      }),
    ).toBe("PostHog task 'deploy' — needs your input");
  });

  it("normalizes an agent-added greeting into the real name", () => {
    expect(
      composeUtterance({
        text: "Hey, blocked on the API key",
        taskTitle: "deploy",
        needsUser: true,
        addressByName: true,
        firstName: "Jon",
      }),
    ).toBe("PostHog task 'deploy' — Hey Jon, blocked on the API key");
  });

  it("does not add a name when it is unknown", () => {
    expect(
      composeUtterance({
        text: "I need your input",
        taskTitle: "deploy",
        needsUser: true,
      }),
    ).toBe("PostHog task 'deploy' — I need your input");
  });

  it("does not double-prefix when the agent already added one", () => {
    expect(
      composeUtterance({
        text: "PostHog task 'x' — already prefixed",
        taskTitle: "y",
      }),
    ).toBe("PostHog task 'x' — already prefixed");
  });

  it("does not double-prefix even when addressing by name", () => {
    expect(
      composeUtterance({
        text: "PostHog task 'x' — already prefixed",
        taskTitle: "y",
        needsUser: true,
        addressByName: true,
        firstName: "Jon",
      }),
    ).toBe("PostHog task 'x' — already prefixed");
  });

  it("truncates a long task title", () => {
    const long = "a".repeat(60);
    const out = composeUtterance({ text: "hi", taskTitle: long });
    expect(out).toContain("…");
    expect(out.length).toBeLessThan(`PostHog task '${long}' — hi`.length);
  });

  it("falls back to the body when there is no task title", () => {
    expect(composeUtterance({ text: "hello", taskTitle: "" })).toBe("hello");
  });
});

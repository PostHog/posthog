import { describe, expect, it } from "vitest";
import type { GhExecResult } from "./gh";
import {
  formatStack,
  type PullRequestRefs,
  type Stack,
  stacksApiError,
  summarizeStackList,
  validateStackChain,
} from "./stacks";

function refs(
  number: number,
  headRef: string,
  baseRef: string,
): PullRequestRefs {
  return { number, headRef, baseRef };
}

describe("validateStackChain", () => {
  it.each([
    {
      name: "accepts a chain where each layer targets the one below it",
      prs: [
        refs(1, "posthog/db", "master"),
        refs(2, "posthog/api", "posthog/db"),
        refs(3, "posthog/ui", "posthog/api"),
      ],
      expected: null,
    },
    {
      name: "accepts a single layer, which cannot break a chain",
      prs: [refs(1, "posthog/db", "master")],
      expected: null,
    },
    {
      name: "rejects a layer opened against the base branch instead of its parent",
      prs: [refs(1, "posthog/db", "master"), refs(2, "posthog/api", "master")],
      expected:
        "#2 targets 'master', but the layer below it (#1) is on 'posthog/db'. " +
        "Every layer must target the branch of the layer below it. " +
        "Retarget #2 onto that branch with `gh pr edit`, then retry.",
    },
  ])("$name", ({ prs, expected }) => {
    expect(validateStackChain(prs)).toBe(expected);
  });

  // Guards against someone restoring the convenient copy-pastable command.
  it("keeps a ref out of any runnable command", () => {
    const problem = validateStackChain([
      refs(1, "feat/x;whoami", "master"),
      refs(2, "posthog/api", "master"),
    ]);
    expect(problem).toContain("feat/x;whoami");
    expect(problem).not.toContain("--base feat/x;whoami");
  });

  it("reports the lowest break when several layers are misaligned", () => {
    const problem = validateStackChain([
      refs(1, "posthog/db", "master"),
      refs(2, "posthog/api", "master"),
      refs(3, "posthog/ui", "master"),
    ]);
    expect(problem).toContain("#2 targets 'master'");
    expect(problem).not.toContain("#3");
  });
});

describe("stacksApiError", () => {
  function result(partial: Partial<GhExecResult>): GhExecResult {
    return { stdout: "", stderr: "", exitCode: 1, ...partial };
  }

  it("explains that a 404 means stacks are off for the repo, not a bad URL", () => {
    const message = stacksApiError(
      result({ stderr: "gh: HTTP 404" }),
      "Creating the stack",
    );
    expect(message).toContain("Creating the stack failed");
    expect(message).toContain("not");
    expect(message).toContain("enabled for this repository");
  });

  it("passes other failures through verbatim so the API's reason survives", () => {
    expect(
      stacksApiError(
        result({ stderr: "gh: HTTP 422 - base ref mismatch" }),
        "Creating the stack",
      ),
    ).toBe("Creating the stack failed: gh: HTTP 422 - base ref mismatch");
  });
});

describe("formatStack", () => {
  const stack: Stack = {
    id: 9,
    number: 50,
    url: "https://api.github.com/repos/x/y/stacks/50",
    base: { ref: "master" },
    open: true,
    pull_requests: [
      {
        number: 11,
        state: "open",
        draft: false,
        merged_at: "2026-08-01T00:00:00Z",
        head: { ref: "posthog/db", sha: "a1" },
      },
      {
        number: 12,
        state: "open",
        draft: true,
        merged_at: null,
        head: { ref: "posthog/api", sha: "b2" },
      },
    ],
  };

  // The agent reads this order back to build the create/extend payload.
  it("numbers the layers bottom to top and marks merged and draft ones", () => {
    expect(formatStack(stack)).toBe(
      "Stack #50 onto master (open), bottom to top:\n" +
        "  1. #11 posthog/db — merged\n" +
        "  2. #12 posthog/api — draft",
    );
  });
});

describe("summarizeStackList", () => {
  function stacks(open: number, closed: number): Stack[] {
    return Array.from({ length: open + closed }, (_, i) => ({
      id: i,
      number: i + 1,
      url: "",
      base: { ref: "master" },
      open: i < open,
      pull_requests: [],
    }));
  }

  // A cut the agent cannot see reads as the whole repository.
  it.each([
    { name: "says nothing when everything is shown", list: stacks(3, 0) },
    {
      name: "names the closed stacks it dropped",
      list: stacks(3, 7),
      expected: "7 closed",
    },
    {
      name: "names the open stacks past the cap",
      list: stacks(25, 0),
      expected: "5 more open",
    },
    {
      name: "names both when it drops open and closed stacks",
      list: stacks(25, 7),
      expected: "5 more open, 7 closed",
    },
  ])("$name", ({ list, expected }) => {
    const text = summarizeStackList(list);
    if (expected === undefined) {
      expect(text).not.toContain("Not shown");
      return;
    }
    expect(text).toContain(`Not shown: ${expected}.`);
  });

  it.each([
    {
      name: "no stacks at all",
      list: [],
      expected: "No stacks in this repository.",
    },
    {
      name: "stacks exist but none are open",
      list: stacks(0, 4),
      expected: "No open stacks in this repository.",
    },
  ])("reports $name", ({ list, expected }) => {
    expect(summarizeStackList(list)).toContain(expected);
  });
});

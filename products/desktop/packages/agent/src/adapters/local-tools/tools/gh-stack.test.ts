import { beforeEach, describe, expect, it, vi } from "vitest";

const createStack = vi.fn();
const extendStack = vi.fn();
const getStack = vi.fn();
const fetchPullRequestRefs = vi.fn();
const unstack = vi.fn();

vi.mock("@posthog/git/stacks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@posthog/git/stacks")>();
  return {
    ...actual,
    createStack: (...args: unknown[]) => createStack(...args),
    extendStack: (...args: unknown[]) => extendStack(...args),
    getStack: (...args: unknown[]) => getStack(...args),
    fetchPullRequestRefs: (...args: unknown[]) => fetchPullRequestRefs(...args),
    unstack: (...args: unknown[]) => unstack(...args),
  };
});

const { ghStackTool } = await import("./gh-stack");

const CTX = { cwd: "/tmp/workspace/repos/posthog/posthog", token: "ghs_x" };

describe("gh_stack tool handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    {
      name: "create with a single pull request",
      args: { operation: "create", pull_requests: [1] },
      expected: "at least 2 PR number(s)",
    },
    {
      name: "create with no pull requests at all",
      args: { operation: "create" },
      expected: "at least 2 PR number(s)",
    },
    {
      name: "create listing the same pull request twice",
      args: { operation: "create", pull_requests: [1, 1] },
      expected: "same PR twice",
    },
    {
      name: "extend without a stack number",
      args: { operation: "extend", pull_requests: [3] },
      expected: "needs `stack`",
    },
    {
      name: "unstack without a stack number",
      args: { operation: "unstack" },
      expected: "needs `stack`",
    },
  ])("refuses $name locally", async ({ args, expected }) => {
    const result = await ghStackTool.handler(CTX, args);

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain(expected);
    expect(createStack).not.toHaveBeenCalled();
    expect(extendStack).not.toHaveBeenCalled();
    expect(unstack).not.toHaveBeenCalled();
  });

  it("refuses to link a chain whose layers do not target each other", async () => {
    fetchPullRequestRefs.mockResolvedValue([
      { number: 1, headRef: "posthog/db", baseRef: "master" },
      { number: 2, headRef: "posthog/api", baseRef: "master" },
    ]);

    const result = await ghStackTool.handler(CTX, {
      operation: "create",
      pull_requests: [1, 2],
    });

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("Retarget #2 onto that branch");
    expect(result.content[0].text).toContain("posthog/db");
    expect(createStack).not.toHaveBeenCalled();
  });

  it("validates an extension against the stack's current top layer", async () => {
    getStack.mockResolvedValue({
      pull_requests: [{ number: 1 }, { number: 2 }],
    });
    fetchPullRequestRefs.mockResolvedValue([
      { number: 2, headRef: "posthog/api", baseRef: "posthog/db" },
      { number: 3, headRef: "posthog/ui", baseRef: "posthog/api" },
    ]);
    extendStack.mockResolvedValue({
      number: 50,
      base: { ref: "master" },
      open: true,
      pull_requests: [],
    });

    await ghStackTool.handler(CTX, {
      operation: "extend",
      stack: 50,
      pull_requests: [3],
    });

    expect(fetchPullRequestRefs).toHaveBeenCalledWith(
      expect.anything(),
      [2, 3],
    );
    expect(extendStack).toHaveBeenCalledWith(expect.anything(), 50, [3]);
  });

  it("surfaces an API failure as a tool error rather than throwing", async () => {
    fetchPullRequestRefs.mockResolvedValue([
      { number: 1, headRef: "posthog/db", baseRef: "master" },
      { number: 2, headRef: "posthog/api", baseRef: "posthog/db" },
    ]);
    createStack.mockRejectedValue(new Error("Creating the stack failed: 403"));

    const result = await ghStackTool.handler(CTX, {
      operation: "create",
      pull_requests: [1, 2],
    });

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toBe("Creating the stack failed: 403");
  });
});

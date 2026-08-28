import { describe, expect, it } from "vitest";
import { resolveChangesLoading } from "./gitQueriesState";

describe("resolveChangesLoading", () => {
  it.each([
    // The validation window: the changed-files query is disabled, so its own
    // isLoading is false, yet the file list is not known. This is the case that
    // used to render a partial diff on first open of a worktree task.
    {
      name: "loads while validateRepo is still in flight",
      input: {
        enabled: true,
        isRepoLoading: true,
        repoEnabled: false,
        changesPending: true,
      },
      expected: true,
    },
    {
      name: "loads while the file list fetches after validation",
      input: {
        enabled: true,
        isRepoLoading: false,
        repoEnabled: true,
        changesPending: true,
      },
      expected: true,
    },
    {
      name: "ready once the file list resolves",
      input: {
        enabled: true,
        isRepoLoading: false,
        repoEnabled: true,
        changesPending: false,
      },
      expected: false,
    },
    {
      name: "ready when the path is not a repo",
      input: {
        enabled: true,
        isRepoLoading: false,
        repoEnabled: false,
        changesPending: true,
      },
      expected: false,
    },
    {
      name: "never loads when disabled",
      input: {
        enabled: false,
        isRepoLoading: true,
        repoEnabled: true,
        changesPending: true,
      },
      expected: false,
    },
  ])("$name", ({ input, expected }) => {
    expect(resolveChangesLoading(input)).toBe(expected);
  });
});

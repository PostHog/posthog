import { Theme } from "@radix-ui/themes";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const selectDirectoryQuery = vi.fn();
const addFolder = vi.fn().mockResolvedValue(undefined);

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    os: { selectDirectory: { query: () => selectDirectoryQuery() } },
  }),
  useHostTRPC: () => ({
    git: { getCurrentBranch: { queryOptions: () => ({}) } },
  }),
}));

vi.mock("@posthog/ui/features/folders/useFolders", () => ({
  useFolders: () => ({
    folders: [],
    getRecentFolders: () => [],
    getFolderDisplayName: () => null,
    addFolder,
    updateLastAccessed: vi.fn(),
    getFolderByPath: vi.fn(),
  }),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ error: vi.fn() }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQueries: () => [],
}));

import type { RegisteredFolder } from "@posthog/ui/features/folders/types";
import { buildFolderRows, FolderPicker } from "./FolderPicker";

/** A promise we resolve by hand, to hold the picker open mid-flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function renderPicker() {
  const onChange = vi.fn();
  render(
    <Theme>
      <FolderPicker variant="field" value="" onChange={onChange} />
    </Theme>,
  );
  return { onChange, trigger: screen.getByRole("button") };
}

describe("FolderPicker", () => {
  afterEach(() => vi.clearAllMocks());

  it("shows feedback synchronously while the dialog is open, then commits the path", async () => {
    // The synchronous "Opening..." state both reassures the user and gives
    // PostHog a DOM mutation, so the open native dialog stops being logged as a
    // dead click.
    const user = userEvent.setup();
    const pending = deferred<string | null>();
    selectDirectoryQuery.mockReturnValue(pending.promise);
    const { onChange, trigger } = renderPicker();

    await user.click(trigger);

    expect(trigger).toHaveTextContent("Opening...");
    expect(trigger).toBeDisabled();

    pending.resolve("/Users/me/code/posthog");

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith("/Users/me/code/posthog"),
    );
    expect(addFolder).toHaveBeenCalledTimes(1);
    expect(trigger).not.toBeDisabled();
  });

  it("ignores re-clicks while a dialog is already open", async () => {
    const user = userEvent.setup();
    const pending = deferred<string | null>();
    selectDirectoryQuery.mockReturnValue(pending.promise);
    const { trigger } = renderPicker();

    await user.click(trigger);
    await user.click(trigger);

    expect(selectDirectoryQuery).toHaveBeenCalledTimes(1);

    pending.resolve(null);
    await waitFor(() => expect(trigger).not.toBeDisabled());
  });
});

describe("buildFolderRows", () => {
  const folder = (
    id: string,
    path: string,
    mainRepoPath: string | null = null,
  ): RegisteredFolder => ({
    id,
    path,
    name: id,
    remoteUrl: "posthog/code",
    lastAccessed: "2026-07-01T00:00:00Z",
    createdAt: "2026-07-01T00:00:00Z",
    mainRepoPath,
  });

  const main = folder("code", "/repos/code");
  const wtA = folder("code-a", "/repos/code-a", "/repos/code");
  const wtB = folder("code-b", "/repos/code-b", "/repos/code");
  const standalone = folder("other", "/repos/other");

  it.each<{
    name: string;
    recents: RegisteredFolder[];
    all: RegisteredFolder[];
    expected: Array<{ id: string; isWorktree: boolean; indented: boolean }>;
  }>([
    {
      name: "a recent worktree pulls in its whole family, main first",
      recents: [wtB],
      all: [wtA, main, wtB, standalone],
      expected: [
        { id: "code", isWorktree: false, indented: false },
        { id: "code-a", isWorktree: true, indented: true },
        { id: "code-b", isWorktree: true, indented: true },
      ],
    },
    {
      name: "families are emitted once even when several members are recent",
      recents: [wtA, main, standalone],
      all: [wtA, main, wtB, standalone],
      expected: [
        { id: "code", isWorktree: false, indented: false },
        { id: "code-a", isWorktree: true, indented: true },
        { id: "code-b", isWorktree: true, indented: true },
        { id: "other", isWorktree: false, indented: false },
      ],
    },
    {
      name: "worktrees without a registered main clone stay top-level",
      recents: [wtA],
      all: [wtA, wtB, standalone],
      expected: [
        { id: "code-a", isWorktree: true, indented: false },
        { id: "code-b", isWorktree: true, indented: false },
      ],
    },
    {
      name: "standalone folders stay single rows",
      recents: [standalone],
      all: [wtA, main, standalone],
      expected: [{ id: "other", isWorktree: false, indented: false }],
    },
  ])("$name", ({ recents, all, expected }) => {
    expect(
      buildFolderRows(recents, all).map((row) => ({
        id: row.folder.id,
        isWorktree: row.isWorktree,
        indented: row.indented,
      })),
    ).toEqual(expected);
  });
});

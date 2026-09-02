import { Theme } from "@radix-ui/themes";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../state/gitInteractionStore", () => ({
  useGitInteractionStore: () => ({ actions: { openBranch: vi.fn() } }),
}));

vi.mock("../utils/getSuggestedBranchName", () => ({
  getSuggestedBranchName: vi.fn(() => null),
}));

vi.mock("../gitCacheKeys", () => ({
  invalidateGitBranchQueries: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    git: {
      getAllBranches: { queryOptions: () => ({}) },
      checkoutBranch: { mutationOptions: () => ({}) },
    },
    workspace: {
      listRepoCheckouts: { queryOptions: () => ({}) },
    },
  }),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({
    gitQueryKey: () => [],
    gitQueryFilter: () => ({}),
    gitPathFilter: () => ({}),
    fsPathFilter: () => ({}),
    fsQueryKey: () => [],
  }),
}));

vi.mock("../../../primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

const mutateMock = vi.fn();
let checkoutMutationOptions: {
  onSuccess?: (result: {
    previousBranch: string;
    currentBranch: string;
  }) => void;
};
let completeCheckout: (result: {
  previousBranch: string;
  currentBranch: string;
}) => void;
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: [], isLoading: false }),
  useMutation: (options: typeof checkoutMutationOptions) => {
    checkoutMutationOptions = options;
    const [result, setResult] = useState<{
      data?: { previousBranch: string; currentBranch: string };
      variables?: { directoryPath: string; branchName: string };
    }>({});
    completeCheckout = (data) => {
      setResult({
        data,
        variables: {
          directoryPath: "/repos/code",
          branchName: data.currentBranch,
        },
      });
      options.onSuccess?.(data);
    };
    return { mutate: mutateMock, ...result };
  },
  useQueryClient: () => ({
    getQueriesData: () => [],
    getQueryData: () => undefined,
  }),
}));

import { BranchSelector } from "./BranchSelector";

function renderInTheme(children: React.ReactElement) {
  return render(<Theme>{children}</Theme>);
}

describe("BranchSelector cloud mode", () => {
  it("keeps the trigger enabled while the initial cloud load is in flight", () => {
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        workspaceMode="cloud"
        cloudBranches={[]}
        cloudBranchesLoading={true}
        cloudSearchQuery=""
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Branch" })).toBeEnabled();
  });

  it("seeds the default branch as a pickable item with a loading row while the cloud list loads", async () => {
    const user = userEvent.setup();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        defaultBranch="main"
        workspaceMode="cloud"
        cloudBranches={[]}
        cloudBranchesLoading={true}
        cloudSearchQuery=""
        selectedBranch="main"
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));

    expect(await screen.findByRole("option", { name: "main" })).toBeVisible();
    expect(screen.getByText("Loading branches…")).toBeVisible();
    // The seeded row makes the list non-empty, so the empty-state stays gated
    // off (Base UI only reveals it when the content group is data-empty) — it
    // keeps the `hidden` class rather than flashing "No branches found." above
    // the trunk row.
    expect(screen.getByText("No branches found.")).toHaveClass("hidden");
  });

  it("does not seed the default branch once the user is searching", async () => {
    const user = userEvent.setup();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        defaultBranch="main"
        workspaceMode="cloud"
        cloudBranches={[]}
        cloudBranchesLoading={true}
        cloudSearchQuery="feat"
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));

    expect(screen.queryByRole("option", { name: "main" })).toBeNull();
  });

  it("re-selects the default when a stale cached default is replaced by the live one", () => {
    const onBranchSelect = vi.fn();
    const { rerender } = renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        defaultBranch="master"
        workspaceMode="cloud"
        cloudBranches={[]}
        cloudBranchesLoading={true}
        cloudSearchQuery=""
        selectedBranch={null}
        onBranchSelect={onBranchSelect}
        onCloudSearchChange={vi.fn()}
      />,
    );

    // Auto-selected the (stale) cached default.
    expect(onBranchSelect).toHaveBeenLastCalledWith("master");

    // Parent commits that selection; then the live default arrives differing.
    rerender(
      <Theme>
        <BranchSelector
          repoPath="owner/repo"
          currentBranch={null}
          defaultBranch="main"
          workspaceMode="cloud"
          cloudBranches={["main"]}
          cloudBranchesLoading={false}
          cloudSearchQuery=""
          selectedBranch="master"
          onBranchSelect={onBranchSelect}
          onCloudSearchChange={vi.fn()}
        />
      </Theme>,
    );

    expect(onBranchSelect).toHaveBeenLastCalledWith("main");
  });

  it("does not override a branch the user picked when the default later changes", () => {
    const onBranchSelect = vi.fn();
    const { rerender } = renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        defaultBranch="master"
        workspaceMode="cloud"
        cloudBranches={["master", "feature-x"]}
        cloudBranchesLoading={false}
        cloudSearchQuery=""
        selectedBranch="feature-x"
        onBranchSelect={onBranchSelect}
        onCloudSearchChange={vi.fn()}
      />,
    );

    rerender(
      <Theme>
        <BranchSelector
          repoPath="owner/repo"
          currentBranch={null}
          defaultBranch="main"
          workspaceMode="cloud"
          cloudBranches={["main", "feature-x"]}
          cloudBranchesLoading={false}
          cloudSearchQuery=""
          selectedBranch="feature-x"
          onBranchSelect={onBranchSelect}
          onCloudSearchChange={vi.fn()}
        />
      </Theme>,
    );

    expect(onBranchSelect).not.toHaveBeenCalled();
  });

  it("surfaces the 'Use input as branch name' action when the typed value is new", async () => {
    const user = userEvent.setup();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        workspaceMode="cloud"
        cloudBranches={["main", "feature-a"]}
        cloudBranchesLoading={false}
        cloudSearchQuery="brand-new-branch"
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));

    expect(
      await screen.findByText('Use "brand-new-branch" as branch name'),
    ).toBeInTheDocument();
  });

  it("hides the typed-name action when the input exactly matches an existing branch", async () => {
    const user = userEvent.setup();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        workspaceMode="cloud"
        cloudBranches={["main", "feature-a"]}
        cloudBranchesLoading={false}
        cloudSearchQuery="main"
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));

    expect(
      screen.queryByText(/Use "main" as branch name/),
    ).not.toBeInTheDocument();
  });

  it("commits the typed value via onBranchSelect when the sentinel action is selected", async () => {
    const user = userEvent.setup();
    const onBranchSelect = vi.fn();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        workspaceMode="cloud"
        cloudBranches={[]}
        cloudBranchesLoading={true}
        cloudSearchQuery="brand-new-branch"
        onBranchSelect={onBranchSelect}
        onCloudSearchChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));
    await user.click(
      await screen.findByText('Use "brand-new-branch" as branch name'),
    );

    expect(onBranchSelect).toHaveBeenCalledWith("brand-new-branch");
  });

  it("invokes onCloudBranchCommit when the typed value is committed (so the parent can reset the search)", async () => {
    const user = userEvent.setup();
    const onCloudBranchCommit = vi.fn();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        workspaceMode="cloud"
        cloudBranches={[]}
        cloudBranchesLoading={true}
        cloudSearchQuery="brand-new-branch"
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
        onCloudBranchCommit={onCloudBranchCommit}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));
    await user.click(
      await screen.findByText('Use "brand-new-branch" as branch name'),
    );

    expect(onCloudBranchCommit).toHaveBeenCalledTimes(1);
  });
});

describe("BranchSelector checkout context", () => {
  it("shows the checked-out branch after an in-place checkout succeeds", () => {
    const { rerender } = renderInTheme(
      <BranchSelector
        repoPath="/repos/code"
        currentBranch="main"
        workspaceMode="local"
      />,
    );

    expect(screen.getByRole("combobox", { name: "Branch" })).toHaveTextContent(
      "main",
    );

    act(() => {
      completeCheckout({
        previousBranch: "main",
        currentBranch: "feature/in-place",
      });
    });

    expect(screen.getByRole("combobox", { name: "Branch" })).toHaveTextContent(
      "feature/in-place",
    );

    rerender(
      <Theme>
        <BranchSelector
          repoPath="/repos/code"
          currentBranch="feature/external"
          workspaceMode="local"
        />
      </Theme>,
    );

    expect(screen.getByRole("combobox", { name: "Branch" })).toHaveTextContent(
      "feature/external",
    );
  });

  it.each([
    {
      name: "local mode shows which checkout the branch switch applies to",
      workspaceMode: "local" as const,
      expectedPrefix: "Branch in",
    },
    {
      name: "worktree mode labels the pick as the base branch for the checkout",
      workspaceMode: "worktree" as const,
      expectedPrefix: "Base branch for",
    },
  ])("$name", async ({ workspaceMode, expectedPrefix }) => {
    const user = userEvent.setup();
    renderInTheme(
      <BranchSelector
        repoPath="/repos/code-wt"
        currentBranch="main"
        workspaceMode={workspaceMode}
        onBranchSelect={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));

    const contextRow = await screen.findByText(expectedPrefix, {
      exact: false,
    });
    expect(contextRow).toHaveTextContent(`${expectedPrefix} code-wt`);
    expect(contextRow).toHaveAttribute("title", "/repos/code-wt");
  });

  it("shows no checkout row in cloud mode (the repo picker sits next to it)", async () => {
    const user = userEvent.setup();
    renderInTheme(
      <BranchSelector
        repoPath="owner/repo"
        currentBranch={null}
        workspaceMode="cloud"
        cloudBranches={["main"]}
        cloudBranchesLoading={false}
        cloudSearchQuery=""
        onBranchSelect={vi.fn()}
        onCloudSearchChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Branch" }));

    expect(screen.queryByText("Branch in", { exact: false })).toBeNull();
    expect(screen.queryByText("Base branch for", { exact: false })).toBeNull();
  });
});

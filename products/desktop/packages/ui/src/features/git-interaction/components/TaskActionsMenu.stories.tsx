import {
  computeGitInteractionState,
  type GitState,
} from "@posthog/core/git-interaction/gitInteractionLogic";
import type { Meta, StoryObj } from "@storybook/react";
import { GitActionControl } from "./TaskActionsMenu";

// Runs the real computeGitInteractionState over a realistic GitState, so the
// stories show exactly what the task header offers in each environment,
// including which actions are dropped rather than disabled.
const baseState: GitState = {
  repoPath: "/Users/dev/example-repo",
  isRepo: true,
  isRepoLoading: false,
  hasChanges: true,
  aheadOfRemote: 2,
  behind: 0,
  aheadOfDefault: 2,
  hasRemote: true,
  isFeatureBranch: true,
  currentBranch: "feature/add-export",
  defaultBranch: "main",
  ghStatus: { installed: true, authenticated: true },
  repoInfo: { owner: "example", repo: "example-repo" },
  prStatus: {
    prExists: false,
    baseBranch: null,
    headBranch: null,
    prUrl: null,
  },
  isOnline: true,
};

function ControlFor({ state }: { state: GitState }) {
  const computed = computeGitInteractionState(state);
  return (
    <div className="flex flex-col gap-3 p-4">
      <GitActionControl
        primaryAction={computed.primaryAction}
        actions={computed.actions}
        isBusy={false}
        onSelect={() => {}}
      />
      <div className="text-(--gray-10) text-[12px]">
        actions: {computed.actions.map((a) => a.id).join(", ")}
        {computed.createPrDisabledReason
          ? ` · create-pr reason: ${computed.createPrDisabledReason}`
          : ""}
      </div>
    </div>
  );
}

const meta: Meta<typeof ControlFor> = {
  title: "Features/GitInteraction/TaskActionsMenu",
  component: ControlFor,
};
export default meta;

type Story = StoryObj<typeof ControlFor>;

export const Ready: Story = {
  render: () => <ControlFor state={baseState} />,
};

/** How a user gets here: onboarding skipped install-cli because GitHub was
 * connected, then they run a local task. */
export const GhCliMissing: Story = {
  render: () => (
    <ControlFor
      state={{
        ...baseState,
        ghStatus: { installed: false, authenticated: false },
      }}
    />
  ),
};

export const GhCliUnauthenticated: Story = {
  render: () => (
    <ControlFor
      state={{
        ...baseState,
        ghStatus: { installed: true, authenticated: false },
      }}
    />
  ),
};

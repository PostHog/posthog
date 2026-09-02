import { CreatePrDialog } from "@posthog/ui/features/git-interaction/components/CreatePrDialog";
import { useGitInteractionStore } from "@posthog/ui/features/git-interaction/state/gitInteractionStore";
import type { CreatePrStep } from "@posthog/ui/features/git-interaction/types";
import type { Meta, StoryObj } from "@storybook/react-vite";

function setStoreState(overrides: {
  branchName?: string;
  commitMessage?: string;
  prTitle?: string;
  prBody?: string;
  createPrOpen?: boolean;
  createPrStep?: CreatePrStep;
  createPrError?: string | null;
  createPrNeedsBranch?: boolean;
  createPrNeedsCommit?: boolean;
  createPrBaseBranch?: string | null;
  createPrDraft?: boolean;
  createPrFailedStep?: CreatePrStep | null;
  isGeneratingCommitMessage?: boolean;
  isGeneratingPr?: boolean;
  isSubmitting?: boolean;
}) {
  useGitInteractionStore.setState({
    branchName: "",
    commitMessage: "",
    prTitle: "",
    prBody: "",
    createPrOpen: true,
    createPrStep: "idle",
    createPrError: null,
    createPrNeedsBranch: false,
    createPrNeedsCommit: false,
    createPrBaseBranch: null,
    createPrDraft: false,
    createPrFailedStep: null,
    isGeneratingCommitMessage: false,
    isGeneratingPr: false,
    isSubmitting: false,
    ...overrides,
  });
}

const noop = () => {};

const meta: Meta<typeof CreatePrDialog> = {
  title: "Git/CreatePrDialog",
  component: CreatePrDialog,
  parameters: { layout: "centered" },
};

export default meta;

export const SetupFull: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsBranch: true,
        createPrNeedsCommit: true,
        createPrBaseBranch: "main",
        branchName: "feature/add-auth",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="main"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const SetupCommitOnly: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsCommit: true,
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 1, linesAdded: 10, linesRemoved: 2 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const SetupPushOnly: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({});
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 0, linesAdded: 0, linesRemoved: 0 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const SetupWithDraft: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsCommit: true,
        createPrDraft: true,
        prTitle: "Add user authentication",
        prBody: "Closes #123",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const SetupWithError: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsBranch: true,
        createPrError: "Branch name is required.",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="main"
      diffStats={{ filesChanged: 1, linesAdded: 5, linesRemoved: 0 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const SetupGeneratingCommitMessage: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsCommit: true,
        isGeneratingCommitMessage: true,
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const SetupGeneratingPr: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsCommit: true,
        isGeneratingPr: true,
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const ExecutingCreatingBranch: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsBranch: true,
        createPrNeedsCommit: true,
        createPrStep: "creating-branch",
        branchName: "feature/add-auth",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="main"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={true}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const ExecutingCommitting: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsBranch: true,
        createPrNeedsCommit: true,
        createPrStep: "committing",
        branchName: "feature/add-auth",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="main"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={true}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const ExecutingPushing: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsCommit: true,
        createPrStep: "pushing",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={true}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const ExecutingCreatingPr: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsCommit: true,
        createPrStep: "creating-pr",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={true}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

export const ExecutingError: StoryObj<typeof CreatePrDialog> = {
  decorators: [
    (Story) => {
      setStoreState({
        createPrNeedsBranch: true,
        createPrNeedsCommit: true,
        createPrStep: "error",
        createPrError: "Failed to push: remote rejected (permission denied)",
        createPrFailedStep: "pushing",
        branchName: "feature/add-auth",
      });
      return <Story />;
    },
  ],
  render: () => (
    <CreatePrDialog
      open={true}
      onOpenChange={noop}
      currentBranch="main"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      isSubmitting={false}
      onSubmit={noop}
      onGenerateCommitMessage={noop}
      onGeneratePr={noop}
    />
  ),
};

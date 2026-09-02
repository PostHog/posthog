import {
  GitCommitDialog,
  GitPushDialog,
} from "@posthog/ui/features/git-interaction/components/GitInteractionDialogs";
import { Flex } from "@radix-ui/themes";
import type { Meta, StoryObj } from "@storybook/react-vite";

function DialogShowcase() {
  return <Flex direction="column" gap="4" />;
}

const meta: Meta<typeof DialogShowcase> = {
  title: "Git/Dialogs",
  component: DialogShowcase,
  parameters: { layout: "centered" },
};

export default meta;

export const CommitDefault: StoryObj<typeof GitCommitDialog> = {
  render: () => (
    <GitCommitDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      commitMessage=""
      onCommitMessageChange={() => {}}
      nextStep="commit"
      onNextStepChange={() => {}}
      pushDisabledReason={null}
      onContinue={() => {}}
      isSubmitting={false}
      error={null}
      onGenerateMessage={() => {}}
      isGeneratingMessage={false}
    />
  ),
};

export const CommitWithMessage: StoryObj<typeof GitCommitDialog> = {
  render: () => (
    <GitCommitDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      commitMessage="Add user authentication flow"
      onCommitMessageChange={() => {}}
      nextStep="commit-push"
      onNextStepChange={() => {}}
      pushDisabledReason={null}
      onContinue={() => {}}
      isSubmitting={false}
      error={null}
      onGenerateMessage={() => {}}
      isGeneratingMessage={false}
    />
  ),
};

export const CommitSubmitting: StoryObj<typeof GitCommitDialog> = {
  render: () => (
    <GitCommitDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      commitMessage="Add feature"
      onCommitMessageChange={() => {}}
      nextStep="commit"
      onNextStepChange={() => {}}
      pushDisabledReason={null}
      onContinue={() => {}}
      isSubmitting={true}
      error={null}
      onGenerateMessage={() => {}}
      isGeneratingMessage={false}
    />
  ),
};

export const CommitWithError: StoryObj<typeof GitCommitDialog> = {
  render: () => (
    <GitCommitDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      commitMessage="Add feature"
      onCommitMessageChange={() => {}}
      nextStep="commit"
      onNextStepChange={() => {}}
      pushDisabledReason={null}
      onContinue={() => {}}
      isSubmitting={false}
      error="Failed to commit: pre-commit hook failed"
      onGenerateMessage={() => {}}
      isGeneratingMessage={false}
    />
  ),
};

export const CommitWithLongPreCommitError: StoryObj<typeof GitCommitDialog> = {
  render: () => (
    <GitCommitDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      commitMessage="Add feature"
      onCommitMessageChange={() => {}}
      nextStep="commit"
      onNextStepChange={() => {}}
      pushDisabledReason={null}
      onContinue={() => {}}
      isSubmitting={false}
      error={`[STARTED] Backing up original state... [COMPLETED] Backed up original state in git stash (cad5bdf02e45017c4afcd82b0c05240f3a134713) [STARTED] Running tasks for staged files... [STARTED] package.json — 2 files [STARTED] *.{ts,tsx,js,jsx} — 2 files [STARTED] biome check --write --unsafe --files-ignore-unknown=true --no-errors-on-unmatched [COMPLETED] biome check --write --unsafe --files-ignore-unknown=true --no-errors-on-unmatched [STARTED] bash -c 'pnpm typecheck' [FAILED] bash -c 'pnpm typecheck' [FAILED] [FAILED] bash -c 'pnpm typecheck' [FAILED] [COMPLETED] Running tasks for staged files... [STARTED] Applying modifications from tasks... [SKIPPED] Skipped because of errors from tasks. [STARTED] Reverting to original state because of errors... [COMPLETED] Reverting to original state because of errors... [STARTED] Cleaning up temporary files... [COMPLETED] Cleaning up temporary files...

✖ bash -c 'pnpm typecheck':
src/renderer/features/git-interaction/components/GitInteractionDialogs.stories.tsx(373,7): error TS2322: Type '{ open: true; onOpenChange: () => void; baseBranch: string; headBranch: string; title: string; onTitleChange: () => void; body: string; onBodyChange: () => void; onConfirm: () => void; asdff: true; isSubmitting: false; error: string; onGenerate: () => void; isGenerating: false; }' is not assignable to type 'IntrinsicAttributes & GitPrDialogProps'.
  Property 'asdff' does not exist on type 'IntrinsicAttributes & GitPrDialogProps'.

Tasks: 8 successful, 9 total
Cached: 8 cached, 9 total
Time: 5.801s
Failed: @posthog/code#typecheck

husky - pre-commit script failed (code 1)`}
      onGenerateMessage={() => {}}
      isGeneratingMessage={false}
    />
  ),
};

export const CommitGenerating: StoryObj<typeof GitCommitDialog> = {
  render: () => (
    <GitCommitDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      diffStats={{ filesChanged: 3, linesAdded: 42, linesRemoved: 12 }}
      commitMessage=""
      onCommitMessageChange={() => {}}
      nextStep="commit"
      onNextStepChange={() => {}}
      pushDisabledReason={null}
      onContinue={() => {}}
      isSubmitting={false}
      error={null}
      onGenerateMessage={() => {}}
      isGeneratingMessage={true}
    />
  ),
};

export const PushIdle: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="push"
      state="idle"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

export const PushSubmitting: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="push"
      state="idle"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={true}
    />
  ),
};

export const PushSuccess: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="push"
      state="success"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

export const PushError: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="push"
      state="error"
      error="Failed to push: remote rejected (permission denied)"
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

export const SyncIdle: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="sync"
      state="idle"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

export const SyncSuccess: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="sync"
      state="success"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

export const PublishIdle: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="publish"
      state="idle"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

export const PublishSuccess: StoryObj<typeof GitPushDialog> = {
  render: () => (
    <GitPushDialog
      open={true}
      onOpenChange={() => {}}
      branchName="feature/add-auth"
      mode="publish"
      state="success"
      error={null}
      onConfirm={() => {}}
      onClose={() => {}}
      isSubmitting={false}
    />
  ),
};

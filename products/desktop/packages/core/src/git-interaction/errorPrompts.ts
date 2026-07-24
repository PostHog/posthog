import type { CreatePrStep } from "./types";

export interface FixWithAgentPrompt {
  label: string;
  context: string;
}

export function buildCreatePrFlowErrorPrompt(
  failedStep: CreatePrStep | null,
): FixWithAgentPrompt {
  return {
    label: `Fix PR creation error`,
    context: `The user tried to create a pull request using the Create PR button in the UI, but it failed at the ${failedStep} step.

This flow is supposed to follow these steps:
1. [creating-branch] Create a new feature branch, if needed (required if on default branch, optional otherwise)
2. [committing] Commit changes
3. [pushing] Push to remote
4. [creating-pr] Create PR

When an error occurs, the app automatically performs a rollback. This means you are likely in the pre-error state, e.g. back on the user's original branch without any new commits.

Rollback scenarios:
1. Branch creation fails -> check out user's original branch
2. Commit fails -> use git reset to get back to the user's original state

Common errors and resolutions:
- **Duplicate branch names** - guide the user towards using a different branch name, or sorting out any git issues that have led them to this state
- **Commit hook failures** - this may be the result of missing dependencies, check failure (e.g. lints), or something else. Ensure you fully understand the issue before proceeding.

Your task is to help the user diagnose and fix the underlying issue (e.g. resolve merge conflicts, fix authentication, clean up git state).

IMPORTANT:
- Do NOT attempt to complete the PR flow yourself (no commit, push, or gh pr create). The user will retry via the "Create PR" button once the issue is resolved.
- You may fix the underlying issue, but always confirm destructive actions with the user first.
- Start by diagnosing: run read-only commands to understand the current state before taking action.
- When the issue is resolved, remind the user to retry by clicking the "Create PR" button in the UI.`,
  };
}

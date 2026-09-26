export const APP_WINDOW_ARG = "--posthog-app-window";
export const ARTIFACT_PREVIEW_ARG = "--posthog-artifact-preview";
export const ARTIFACT_OPEN_EXTERNAL_CHANNEL = "posthog-artifact-open-external";
export const ARTIFACT_HOST_TO_PREVIEW_CHANNEL = "posthog-artifact-host-message";
export const ARTIFACT_PREVIEW_TO_HOST_CHANNEL = "posthog-artifact-message";
export const ARTIFACT_PREVIEW_DATA_URL_PREFIX =
  "data:text/html;charset=utf-8;base64,";
export const ARTIFACT_PREVIEW_PARTITION_PREFIX = "artifact-preview-";
export const TASK_PREVIEW_PARTITION = "task-preview";
export const TASK_PREVIEW_TOKEN_PARAM = "_modal_connect_token";
export const TASK_PREVIEW_ARG = "--posthog-task-preview";
export const TASK_PREVIEW_TO_HOST_CHANNEL = "posthog-task-preview-message";
export const HOST_TO_TASK_PREVIEW_CHANNEL = "posthog-task-preview-host-message";
export const WORKTREES_DIR = ".posthog-desktop/worktrees";
export const PREVIOUS_WORKTREES_DIR = ".posthog-code/worktrees";
export const LEGACY_DATA_DIRS = [
  ".twig",
  ".twig/worktrees",
  ".twig/workspaces",
  ".array",
];

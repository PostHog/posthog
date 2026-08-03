export {
  BILLING_FLAG,
  DISCOVERY_RUN_FLAG,
  EXPERIMENT_SUGGESTIONS_FLAG,
  SYNC_CLOUD_TASKS_FLAG,
} from "./flags";

export const SELF_DRIVING_SETUP_TASK_FLAG =
  "posthog-code-self-driving-setup-task";
export const BRANCH_PREFIX = "posthog-code/";
export const POSTHOG_CODE_INTERNAL_CHILD_ENV = "POSTHOG_CODE_INTERNAL_CHILD";

// Mirrors --color-background (dark) in packages/ui globals.css, for surfaces
// that cannot read CSS variables: the Electron window and the boot error screen.
export const DARK_APP_BACKGROUND_COLOR = "#131316";

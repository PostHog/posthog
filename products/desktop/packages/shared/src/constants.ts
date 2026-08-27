export {
  BILLING_FLAG,
  DISCOVERY_RUN_FLAG,
  EXPERIMENT_SUGGESTIONS_FLAG,
} from "./flags";

export const SELF_DRIVING_SETUP_TASK_FLAG =
  "posthog-code-self-driving-setup-task";
export const BRANCH_PREFIX = "posthog/";
export const POSTHOG_CODE_INTERNAL_CHILD_ENV = "POSTHOG_CODE_INTERNAL_CHILD";

/**
 * Names the tools a custom sandbox image carries. The image spec builder
 * writes it into the image's env; the agent reads it at session start, since
 * nothing else tells it what was installed.
 */
export const IMAGE_TOOLS_ENV_KEY = "POSTHOG_IMAGE_TOOLS";

// Mirrors --color-background (dark) in packages/ui globals.css, for surfaces
// that cannot read CSS variables: the Electron window and the boot error screen.
export const DARK_APP_BACKGROUND_COLOR = "#131316";

import featureFlagKeys from "./feature-flag-keys.json" with { type: "json" };

export const SELF_DRIVING_SETUP_TASK_FLAG =
  featureFlagKeys.SELF_DRIVING_SETUP_TASK_FLAG;
export const POSTHOG_CODE_INTERNAL_CHILD_ENV = "POSTHOG_CODE_INTERNAL_CHILD";

export { IMAGE_TOOLS_ENV_KEY } from "./sandbox-env";

// Mirrors --color-background (dark) in packages/ui globals.css, for surfaces
// that cannot read CSS variables: the Electron window and the boot error screen.
export const DARK_APP_BACKGROUND_COLOR = "#131316";

export {
  BILLING_FLAG,
  DISCOVERY_RUN_FLAG,
  EXPERIMENT_SUGGESTIONS_FLAG,
} from "./flags";

export const SELF_DRIVING_SETUP_TASK_FLAG =
  "posthog-code-self-driving-setup-task";
export const BRANCH_PREFIX = "posthog/";

// Cap on personalization instructions, hand-typed or synced from an
// AGENTS.md/CLAUDE.md. Shared by the settings textarea, `OsService`'s file
// truncation and the session-start Zod validators (`startSessionInput`/
// `reconnectSessionInput`) so the three stay equal — a synced file truncated
// to this length must not then fail the session-start length check.
export const USER_AGENT_INSTRUCTIONS_MAX_LENGTH = 20_000;

export const POSTHOG_CODE_INTERNAL_CHILD_ENV = "POSTHOG_CODE_INTERNAL_CHILD";

// Mirrors --color-background (dark) in packages/ui globals.css, for surfaces
// that cannot read CSS variables: the Electron window and the boot error screen.
export const DARK_APP_BACKGROUND_COLOR = "#131316";

export const BILLING_FLAG = "posthog-code-billing";
export const EXPERIMENT_SUGGESTIONS_FLAG =
  "posthog-code-experiment-suggestions";
export const SELF_DRIVING_SETUP_TASK_FLAG =
  "posthog-code-self-driving-setup-task";
export const DISCOVERY_RUN_FLAG = "posthog-code-discovery-run";
export const BRANCH_PREFIX = "posthog/";
export const APP_WINDOW_ARG = "--posthog-app-window";
export const QUICK_ASK_WINDOW_ARG = "--posthog-quick-ask-window";
export const QUICK_ASK_HIDE_CHANNEL = "posthog-quick-ask-hide";
export const QUICK_ASK_RESIZE_CHANNEL = "posthog-quick-ask-resize";
export const QUICK_ASK_OPEN_IN_APP_CHANNEL = "posthog-quick-ask-open-in-app";
export const QUICK_ASK_SHOWN_CHANNEL = "posthog-quick-ask-shown";
export const QUICK_ASK_SHAKE_CHANNEL = "posthog-quick-ask-shake";
export const QUICK_ASK_ASK_CHANNEL = "posthog-quick-ask-ask";
export const QUICK_ASK_CANCEL_CHANNEL = "posthog-quick-ask-cancel";
export const QUICK_ASK_RESET_CHANNEL = "posthog-quick-ask-reset";
export const QUICK_ASK_EVENT_CHANNEL = "posthog-quick-ask-event";
export const QUICK_ASK_LAYOUT_CHANNEL = "posthog-quick-ask-layout";
export const QUICK_ASK_DRAG_START_CHANNEL = "posthog-quick-ask-drag-start";
export const QUICK_ASK_DRAG_END_CHANNEL = "posthog-quick-ask-drag-end";
export const QUICK_ASK_CAPTURE_CHANNEL = "posthog-quick-ask-capture";
export const QUICK_ASK_ATTACHMENT_CHANNEL = "posthog-quick-ask-attachment";
export const QUICK_ASK_DISCARD_ATTACHMENT_CHANNEL =
  "posthog-quick-ask-discard-attachment";
export const QUICK_ASK_ANNOTATE_WINDOW_ARG = "--posthog-quick-ask-annotate";
export const QUICK_ASK_ANNOTATE_SHOT_CHANNEL = "posthog-quick-ask-shot";
export const QUICK_ASK_SCREEN_SETTINGS_CHANNEL =
  "posthog-quick-ask-screen-settings";
export const QUICK_ASK_ANNOTATE_DONE_CHANNEL = "posthog-quick-ask-annotated";

/** Sent to the panel when a screenshot is ready to attach (or cleared). */
export interface QuickAskAttachmentPayload {
  /** Preview for the chip; the full image stays in the main process. */
  previewDataUrl: string | null;
  /** Why capture produced nothing, e.g. missing screen-recording consent. */
  error?: string;
  /** The OS has a settings pane that grants the missing permission. */
  canOpenSettings?: boolean;
}

/**
 * Payload contracts for the quick-ask IPC channels. The preload and the main
 * process must import these instead of retyping the shapes: the two sides
 * are compiled separately, so a shape change that touches only one of them
 * is invisible to the typechecker and fails silently at runtime.
 */
export interface QuickAskResizePayload {
  width: number;
  height: number;
}

export interface QuickAskDragStartPayload {
  /** Grab offset from the window's top-left corner, in CSS pixels. */
  dx: number;
  dy: number;
}

export interface QuickAskLayoutPayload {
  /** Card renders above the pill (anchor sits low on the screen). */
  flip: boolean;
  /** Room between the pill's anchor and the screen edge, in CSS pixels. */
  maxHeight: number;
}
export const ARTIFACT_PREVIEW_ARG = "--posthog-artifact-preview";
export const ARTIFACT_OPEN_EXTERNAL_CHANNEL = "posthog-artifact-open-external";
export const ARTIFACT_HOST_TO_PREVIEW_CHANNEL = "posthog-artifact-host-message";
export const ARTIFACT_PREVIEW_TO_HOST_CHANNEL = "posthog-artifact-message";
export const ARTIFACT_PREVIEW_DATA_URL_PREFIX =
  "data:text/html;charset=utf-8;base64,";
export const ARTIFACT_PREVIEW_PARTITION_PREFIX = "artifact-preview-";
export const DATA_DIR = ".posthog-code";
export const WORKTREES_DIR = ".posthog-code/worktrees";
export const LEGACY_DATA_DIRS = [
  ".twig",
  ".twig/worktrees",
  ".twig/workspaces",
  ".array",
];

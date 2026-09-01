import type {
  CanvasPromptSentProperties,
  CanvasPromptSurface,
  ContextActionProperties,
} from "@posthog/shared/analytics-events";

/** The dashboardId a canvas thread persists to ("dashboard:<id>" → "<id>"). */
export function dashboardIdFromThread(threadId: string): string {
  return threadId.replace(/^dashboard:/, "");
}

/**
 * Build the properties for a `CANVAS_PROMPT_SENT` event. Resolves the
 * dashboard id from the thread id, measures the prompt length, and folds in
 * the suggestion / intent context.
 */
export function buildCanvasPromptProps(opts: {
  surface: CanvasPromptSurface;
  threadId: string;
  text: string;
  fromSuggestion: boolean;
  intent?: "ask_agent_to_fix";
}): CanvasPromptSentProperties {
  return {
    surface: opts.surface,
    dashboard_id: dashboardIdFromThread(opts.threadId),
    from_suggestion: opts.fromSuggestion,
    prompt_length_chars: opts.text.length,
    ...(opts.intent ? { intent: opts.intent } : {}),
  };
}

/**
 * Build the properties for a `save_version` `CONTEXT_ACTION` event. A channel
 * with no published instructions yet is publishing its first version.
 */
export function buildContextSaveProps(opts: {
  channelId: string;
  hasInstructions: boolean;
  success: boolean;
}): ContextActionProperties {
  return {
    action_type: "save_version",
    channel_id: opts.channelId,
    is_first_version: !opts.hasInstructions,
    success: opts.success,
  };
}

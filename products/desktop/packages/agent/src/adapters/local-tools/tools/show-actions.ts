import { showActionSchema } from "@posthog/shared";
import { z } from "zod";
import { defineLocalTool, type LocalToolResult } from "../registry";

export const SHOW_ACTIONS_TOOL_NAME = "show_actions";

export const showActionsSchema = {
  actions: z
    .array(showActionSchema)
    .min(1)
    .max(4)
    .describe("One to four actions, in the order they should appear."),
};

export const SHOW_ACTIONS_TOOL_DESCRIPTION =
  "Show the user a card of clickable buttons in PostHog Desktop, so they can " +
  "act on what you just told them without retyping it. Pass 1 to 4 actions. " +
  "Each action is a typed verb, never a URL: there is no URL parameter and " +
  "free-form URLs are not accepted. " +
  "`compose` opens the new-task composer prefilled with `prompt` (and `repo` " +
  "when given). The user reads, edits and sends it themselves, so it does NOT " +
  "start a task and does NOT send anything on click. " +
  "`open_space` opens a channel's feed. `open_canvas` opens a canvas inside a " +
  "channel, and needs both `channel_id` and `canvas_id`. " +
  "`open_inbox` opens Self-driving, where PostHog files the reports it writes " +
  "on its own. Pass `report_id` to open one report instead of the whole inbox. " +
  "Offer only what the person actually wants to do next, in the order they " +
  "would want it. Buttons that decorate an answer are noise, so skip the call " +
  "entirely when there is nothing worth clicking.";

/**
 * Offers the user buttons; it does not press them. The handler only
 * acknowledges — the desktop renderer draws them off the surfaced `tool_call`
 * and builds the link from the typed action when a button is clicked, so
 * nothing here can reach the user's window anyway.
 *
 * Ungated on purpose. A button the agent never learns it can offer is the
 * whole failure this tool exists to avoid, so it is exposed in every session.
 */
export const showActionsTool = defineLocalTool({
  name: SHOW_ACTIONS_TOOL_NAME,
  description: SHOW_ACTIONS_TOOL_DESCRIPTION,
  schema: showActionsSchema,
  alwaysLoad: true,
  isEnabled: () => true,
  handler: async (): Promise<LocalToolResult> => {
    return { content: [{ type: "text", text: "ok" }] };
  },
});

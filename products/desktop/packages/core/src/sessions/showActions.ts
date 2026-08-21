import {
  type AgentAction,
  readMcpToolDescriptor,
  showActionSchema,
  splitShowAction,
} from "@posthog/shared";

const SHOW_ACTIONS_TOOL = "show_actions";

/** The agent's `show_actions` call, which offers the user buttons to click. */
export function isShowActionsCall(meta: unknown): boolean {
  return readMcpToolDescriptor(meta)?.tool === SHOW_ACTIONS_TOOL;
}

/** One button a `show_actions` call is offering: its text, and the verb behind it. */
export interface ShowActionButton {
  label: string;
  action: AgentAction;
}

/**
 * The buttons to draw for a `show_actions` call. An action that fails the shared
 * schema is dropped rather than drawn, so a button the host would refuse to open
 * is never offered in the first place.
 */
export function readShowActions(rawInput: unknown): ShowActionButton[] {
  if (!rawInput || typeof rawInput !== "object") return [];
  const { actions } = rawInput as { actions?: unknown };
  if (!Array.isArray(actions)) return [];

  return actions.flatMap((entry) => {
    const parsed = showActionSchema.safeParse(entry);
    return parsed.success ? [splitShowAction(parsed.data)] : [];
  });
}

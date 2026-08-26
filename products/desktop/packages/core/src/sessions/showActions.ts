import {
  readMcpToolDescriptor,
  type ShowActionButton,
  showActionSchema,
  splitShowAction,
} from "@posthog/shared";
import { z } from "zod";

const SHOW_ACTIONS_TOOL = "show_actions";
// The local-tools MCP server that hosts show_actions. Mirrors the agent's
// LOCAL_TOOLS_MCP_NAME, hardcoded so core need not import @posthog/agent (same
// reason as SPEAK_TOOL_QUALIFIED_NAME). Matching the server as well as the tool
// keeps a third-party tool that happens to be named "show_actions" out of the
// action-buttons card, where its arguments would fail the schema and the whole
// tool row would vanish from the conversation.
const LOCAL_TOOLS_SERVER = "posthog-code-tools";

/** The agent's `show_actions` call, which offers the user buttons to click. */
export function isShowActionsCall(meta: unknown): boolean {
  const descriptor = readMcpToolDescriptor(meta);
  return (
    descriptor?.server === LOCAL_TOOLS_SERVER &&
    descriptor.tool === SHOW_ACTIONS_TOOL
  );
}

// The envelope only has to be an object holding an array; each entry is judged
// on its own below, so one bad action does not discard the rest.
const showActionsInputSchema = z.object({ actions: z.array(z.unknown()) });

/**
 * The buttons to draw for a `show_actions` call. An action that fails the shared
 * schema is dropped rather than drawn, so a button the host would refuse to open
 * is never offered in the first place.
 */
export function readShowActions(rawInput: unknown): ShowActionButton[] {
  const envelope = showActionsInputSchema.safeParse(rawInput);
  if (!envelope.success) return [];

  return envelope.data.actions.flatMap((entry) => {
    const parsed = showActionSchema.safeParse(entry);
    return parsed.success ? [splitShowAction(parsed.data)] : [];
  });
}

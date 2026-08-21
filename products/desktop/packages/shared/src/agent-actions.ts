import { z } from "zod";

/**
 * An action an agent offers the user as a button. It names a verb and the verb's
 * own fields rather than a URL, and the host builds the link itself with
 * {@link buildActionUrl}. Agent output can carry text from anywhere, so a URL it
 * picked and the user was invited to click would be a phishing primitive.
 *
 * Declared once here because three packages need the same shape and none of them
 * can import the others: the agent's tool schema, the renderer that draws the
 * buttons, and the host procedure that opens one. `describe` text is written for
 * the model reading the tool schema; the other two ignore it.
 */
const requiredField = z.string().trim().min(1);

const composeFields = {
  kind: z.literal("compose"),
  prompt: requiredField.describe(
    "Text to prefill the new-task composer with. The user reads it and sends " +
      "it themselves, so nothing runs on click.",
  ),
  repo: requiredField
    .optional()
    .describe(
      "Repository slug to preselect, e.g. `posthog/posthog`. Omit when the " +
        "task has no repository.",
    ),
};

const openSpaceFields = {
  kind: z.literal("open_space"),
  channel_id: requiredField.describe("Id of the channel whose feed to open."),
};

const openCanvasFields = {
  kind: z.literal("open_canvas"),
  channel_id: requiredField.describe(
    "Id of the channel the canvas lives in. Required.",
  ),
  canvas_id: requiredField.describe("Id of the canvas to open. Required."),
};

/** What the host accepts and {@link buildActionUrl} turns into a link. */
export const agentActionSchema = z.discriminatedUnion("kind", [
  z.object(composeFields),
  z.object(openSpaceFields),
  z.object(openCanvasFields),
]);

export type AgentAction = z.infer<typeof agentActionSchema>;

export const labelSchema = z
  .string()
  .trim()
  .min(1)
  .max(60)
  .describe(
    "Button text. Short and in sentence case, naming what the button does.",
  );

/**
 * One button as the agent offers it: an action plus the text on it. `label`
 * never reaches a link, which is why {@link agentActionSchema} leaves it out.
 */
export const showActionSchema = z.discriminatedUnion("kind", [
  z.object({ ...composeFields, label: labelSchema }),
  z.object({ ...openSpaceFields, label: labelSchema }),
  z.object({ ...openCanvasFields, label: labelSchema }),
]);

export type ShowAction = z.infer<typeof showActionSchema>;

export const openAgentActionInput = z.object({ action: agentActionSchema });

/** One button as the renderer draws it: its text, and the verb behind it. */
export interface ShowActionButton {
  label: string;
  action: AgentAction;
}

/** Split a button back into the text on it and the verb behind it. */
export function splitShowAction(button: ShowAction): ShowActionButton {
  const { label, ...action } = button;
  return { label, action };
}

/**
 * The action is already validated by {@link agentActionSchema}, which rejects a
 * blank required field, so every branch can build a whole link. Keep that
 * guarantee at the schema rather than returning a partial link from here.
 */
export function buildActionUrl(action: AgentAction, scheme: string): string {
  switch (action.kind) {
    case "compose": {
      const prompt = `prompt=${encodeURIComponent(action.prompt)}`;
      const query = action.repo
        ? `${prompt}&repo=${encodeURIComponent(action.repo)}`
        : prompt;
      return `${scheme}://new?${query}`;
    }
    case "open_space":
      return `${scheme}://channel/${encodeURIComponent(action.channel_id)}`;
    case "open_canvas":
      return `${scheme}://canvas/${encodeURIComponent(action.channel_id)}/${encodeURIComponent(action.canvas_id)}`;
  }
}

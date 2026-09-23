import type { SessionActivityEvent } from "../sessions/sessionActivity";

export function voiceConversationContext(
  events: readonly SessionActivityEvent[],
): { context: string; reply: string; replyKey: string } {
  const messages: { role: string; text: string }[] = [];
  let reply = "";
  let replyKey = "";
  for (const event of events.slice(-300)) {
    if (event.type !== "session_update") continue;
    const update = event.notification.update;
    if (update?.content?.type !== "text") continue;
    const kind = update.sessionUpdate;
    if (
      kind !== "user_message_chunk" &&
      kind !== "agent_message_chunk" &&
      kind !== "agent_message"
    )
      continue;
    const role = kind === "user_message_chunk" ? "User" : "Agent";
    const text = update.content.text;
    const previous = messages.at(-1);
    if (kind === "agent_message" && previous?.role === role)
      previous.text = text;
    else if (previous?.role === role) previous.text += text;
    else messages.push({ role, text });
    replyKey = role === "Agent" ? `${event.ts}:${text}` : "";
    reply = role === "Agent" ? (messages.at(-1)?.text ?? "") : "";
  }
  return {
    context: messages
      .map(({ role, text }) => `${role}: ${text}`)
      .join("\n")
      .slice(-8000),
    reply,
    replyKey,
  };
}

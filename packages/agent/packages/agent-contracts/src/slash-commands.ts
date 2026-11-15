/**
 * The leading slash command in a line of prompt text, or undefined when the text
 * does not open with one. The token runs to the first whitespace, so `/clearcache`
 * is its own command rather than a `/clear` carrying trailing text.
 *
 * The agent adapter and the desktop client both dispatch on this and have to agree.
 * When they disagree the failure is silent: either a conversation boundary gets
 * recorded that the agent would ignore, or a sandbox boots for a message the agent
 * would have handled on its own.
 *
 * Core's `parseCommandLine` (message-editor/commands.ts) is the other command
 * parser: it splits a whole single-line invocation into name and args and rejects
 * multiline text, which makes it wrong for dispatch parity with the agent.
 */
export function leadingSlashCommand(
  text: string | undefined,
): string | undefined {
  return text?.match(/^(\/\S+)/)?.[1];
}

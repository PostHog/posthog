import type { PromptRequest } from "@agentclientprotocol/sdk";

/**
 * True when a prompt block was injected by the host rather than typed by the
 * user — a cloud resume preamble, a shell-execute recap. Hosts mark their own
 * injections with `_meta.ui.hidden` so the parts that reason about what the user
 * actually said (slash-command detection, transcript echoes) can skip them.
 */
export function isHiddenPromptBlock(
  block: PromptRequest["prompt"][number],
): boolean {
  const meta = block._meta as { ui?: { hidden?: boolean } } | undefined;
  return meta?.ui?.hidden === true;
}

/** The prompt with host-injected blocks dropped: what the user actually sent. */
export function visiblePromptBlocks(
  prompt: PromptRequest["prompt"],
): PromptRequest["prompt"] {
  return prompt.filter((block) => !isHiddenPromptBlock(block));
}

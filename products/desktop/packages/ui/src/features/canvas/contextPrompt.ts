// Builds the prompt for the task that generates a context's CONTEXT.md. The
// task runs as a normal repo-less agent task (no repo picked up front), so the
// agent has full tools; this is the task's content (its first user message).
// CONTEXT.md is not a file on disk — it lives in PostHog — so the agent must
// publish the result via the PostHog MCP rather than writing a file.
//
// The task starts in plan mode: the agent investigates and proposes a plan for
// the document, the user shapes it, and only once the plan is approved does the
// agent publish. The user's own description of what the context is about seeds
// that plan.
// Title given to the plan task that builds a context's CONTEXT.md. The prefix
// doubles as the marker surfaces use to spot an in-flight build in a channel's
// task feed — the only task↔context.md tie we have until the backend links
// them explicitly.
export const CONTEXT_MD_TASK_TITLE_PREFIX = "Build CONTEXT.md";

export function contextMdTaskTitle(channelName: string): string {
  return `${CONTEXT_MD_TASK_TITLE_PREFIX} for ${channelName}`;
}

export function buildContextGenerationPrompt(input: {
  channelName: string;
  channelId: string;
  description?: string;
}): string {
  const { channelName, channelId, description } = input;
  const seed = description?.trim()
    ? `\nThe user describes what this channel is about:
"""
${description.trim()}
"""
Treat this as the primary guide for what CONTEXT.md should cover — start from it,
then verify and fill it out against the sources below.\n`
    : "";
  return `Build a CONTEXT.md for the channel "${channelName}".
${seed}
CONTEXT.md tells future agents the specific, non-obvious details they need to
work in "${channelName}": what it is, key files, conventions, gotchas, and the
PostHog resources that relate to it.

You are in plan mode. Investigate first, then propose a plan for the document and
let the user refine it before you publish. Investigate two sources:
1. The relevant repository — use Read, Grep, and Glob to find code, directories,
   and config related to "${channelName}" (conventions, key files, gotchas). No
   repo is attached up front: if one isn't already available and you can't infer
   which to use, ask the user which repository to look at before continuing.
2. PostHog — use the PostHog MCP to find data related to "${channelName}" in
   this project: feature flags, experiments, surveys, notebooks, insights, web
   analytics, and persons. Operate only on this project.

Once the plan is approved, PUBLISH the document by calling the PostHog MCP
tool \`desktop-file-system-instructions-partial-update\` exactly once with:
- id: "${channelId}"
- content: the full CONTEXT.md markdown
- base_version: the current instructions version, or 0 if none exists yet

Structure the markdown with these sections:
1. Overview — what "${channelName}" is and why it exists.
2. Key files — the most important paths, each with a one-line purpose.
3. Conventions & gotchas — non-obvious rules, patterns, and pitfalls.
4. Related PostHog resources — relevant flags/experiments/surveys/notebooks/
   insights with links.

Write the document in terse, high-signal language: drop articles and filler,
prefer fragments and short phrases over full sentences, cut anything that does
not carry technical substance. Keep it concise. CONTEXT.md lives in PostHog, not
on disk, so publishing via the MCP tool is what saves it — do not just write a
local file.`;
}

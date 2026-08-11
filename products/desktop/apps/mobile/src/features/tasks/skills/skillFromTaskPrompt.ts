/**
 * Prompt behind the task-detail "Create skill from task" action. It runs inside
 * the task's own session, so the conversation the agent must distill is already
 * its context — the prompt only supplies the contract for the result.
 *
 * Limits mirror the server: `name` is validated as lowercase kebab-case up to
 * 64 characters, `description` up to 4096. Naming them here keeps the agent
 * from discovering them through a failed tool call.
 */

const MAX_NAME_LENGTH = 64;
const MAX_DESCRIPTION_LENGTH = 4096;

export function buildCreateSkillFromTaskPrompt(options?: {
  taskTitle?: string | null;
}): string {
  const title = options?.taskTitle?.trim();
  const subject = title
    ? `this task ("${title}") and the conversation above`
    : "this task and the conversation above";

  return `Turn ${subject} into a reusable team skill.

Distill what we did into a method someone could follow on a *different* instance of the same kind of problem. Generalize: strip out this task's specific names, ids, paths, and one-off details, and keep the approach, the order of steps, the checks that mattered, and the traps worth avoiding. If nothing here generalizes — the work was a one-off with no repeatable method — say so plainly and create nothing.

Then create it with the \`create_llm_skill\` MCP tool:

- \`name\`: lowercase letters, numbers, and hyphens only, at most ${MAX_NAME_LENGTH} characters, no leading, trailing, or consecutive hyphens. Name it after the method, not this task. Run \`list_llm_skills\` first and pick a different name if it is taken — creation fails on a duplicate.
- \`description\`: at most ${MAX_DESCRIPTION_LENGTH} characters, and ideally a couple of sentences. State what the skill does *and* when someone should reach for it — it is the only thing visible when the agent is deciding which skill to load.
- \`body\`: the method as markdown, written as step-by-step instructions to a future agent. Lead with when to use it, then the steps in order, then the failure modes we actually hit. Keep it scannable.

When you are done, reply with the skill name you created and a one-line summary of what it covers. If the tool call fails, tell me the error rather than retrying with a different shape.`;
}

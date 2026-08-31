export interface TaskContextInput {
  taskId: string;
  cwd: string;
  customInstructions?: string;
  additionalDirectories?: string[];
  channelMode?: boolean;
}

export interface TaskContext extends TaskContextInput {
  projectId: number;
  apiHost: string;
  environment: "local" | "cloud";
  additionalInstructions?: string;
}

export interface TaskPromptCapabilities {
  structuredInput?: boolean;
  repositoryTools?: boolean;
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

export function buildPostHogContextPrompt(
  context: Pick<TaskContext, "projectId" | "apiHost">,
): string {
  return `PostHog context: use project ${context.projectId} on ${context.apiHost}. When using PostHog MCP tools, operate only on this project.`;
}

export function buildTaskContextPrompt(taskId: string): string {
  return `## Task context
This is task ${taskId}. Keep material provided as task context, including customer conversations, support tickets, logs, and internal threads, out of code, tests, comments, commit messages, and pull request text. Rewriting or anonymizing that material does not make it safe to publish.`;
}

export function buildAttributionPrompt(
  taskId: string,
  environment: TaskContext["environment"],
): string {
  const commitInstructions =
    environment === "cloud"
      ? `In cloud tasks, call \`git_signed_commit\` to create commits. It automatically adds these trailers:
  Generated-By: PostHog Desktop
  Task-Id: ${taskId}`
      : `Add the following trailers to every commit message after a blank line:
  Generated-By: PostHog Desktop
  Task-Id: ${taskId}

Example:
\`\`\`
git commit -m "$(cat <<'EOF'
fix: resolve login redirect loop

Generated-By: PostHog Desktop
Task-Id: ${taskId}
EOF
)"
\`\`\``;

  return `## Attribution
Do NOT use Claude Code's default attribution (no "Co-Authored-By" trailers, no "Generated with [Claude Code]" lines).

${commitInstructions}

When creating new branches, prefix them with \`posthog/\` (e.g. \`posthog/fix-login-redirect\`).

When creating pull requests, add the following footer at the end of the PR description:
\`\`\`
---
*Created with [PostHog Desktop](https://posthog.com/desktop?ref=pr)*
\`\`\``;
}

export function buildLocalAttributionPrompt(taskId: string): string {
  return buildAttributionPrompt(taskId, "local");
}

export function buildQuestionsPrompt(
  structuredInputAvailable: boolean,
): string {
  if (structuredInputAvailable) {
    return `## Questions
When you need an answer from the user before you can continue, use the structured user-input tool available in your current mode. Never end a turn with a blocking question in a normal assistant message because plain-text questions mark the task as finished instead of waiting for the user's response.`;
  }

  return `## Questions
When you need an answer before you can continue, ask one concise blocking question and stop.`;
}

export function buildPullRequestLinksPrompt(): string {
  return `## Pull request links
When you mention a pull request in any reply or summary, always hyperlink it to its full URL (e.g. a Markdown link like [#123](https://github.com/org/repo/pull/123)) rather than plain text, so readers can open it directly.`;
}

export function buildShellEfficiencyPrompt(): string {
  return `## Shell efficiency
Optimize for the fewest shell round trips.
- Batch related commands into one Bash invocation using \`&&\` (e.g. \`npm run typecheck && npm run lint && npm test\`).
- Emit all independent tool calls in the same response.
- Read multiple files at once.
- Never rerun a command solely to reproduce output you already have.`;
}

export function buildChannelPrompt(repositoryToolsAvailable: boolean): string {
  if (!repositoryToolsAvailable) {
    return `## Channel task
This task may not need a repository. Treat the working directory as task-specific scratch space and do not use another checkout.`;
  }

  return `## Channel task (no repository attached)
You are running in a PostHog channel as a general-purpose assistant. This task may not need a code repository. It could be data analysis via PostHog tools, drafting a message, or answering a question. Do not assume you need a repo.

- Your working directory is a scratch directory, not a git checkout. Treat it as empty.
- Decide from the user's request and the channel CONTEXT.md, if present, whether the task requires a code repository. If it doesn't, do the work in the scratch directory.
- Do not \`cd\` into or edit an existing checkout elsewhere on the machine. Another task may be using it.

If a repository is required, call \`list_repos\` to find it, then use \`clone_repo\` with its \`owner/repo\`. The tool creates a task-specific clone inside the scratch directory and returns the path to use. If you cannot confidently identify the repository, ask the user which repository to clone.`;
}

export function buildCustomInstructionsPrompt(
  customInstructions: string,
): string {
  return `User custom instructions:\n${customInstructions}`;
}

export function buildAdditionalDirectoriesPrompt(
  additionalDirectories: string[],
): string {
  const directories = additionalDirectories
    .map((directory) => `  <directory>${escapeXml(directory)}</directory>`)
    .join("\n");

  return `The user has granted you access to additional directories outside the working directory. You may read and edit files in these paths just like the working directory:
<additional_directories>
${directories}
</additional_directories>`;
}

export function buildTaskSystemPrompt(
  context: TaskContext,
  capabilities: TaskPromptCapabilities = {},
): string {
  const sections = [
    buildPostHogContextPrompt(context),
    buildTaskContextPrompt(context.taskId),
  ];

  sections.push(
    buildAttributionPrompt(context.taskId, context.environment),
    buildQuestionsPrompt(capabilities.structuredInput === true),
    buildPullRequestLinksPrompt(),
    buildShellEfficiencyPrompt(),
  );

  if (context.channelMode) {
    sections.push(buildChannelPrompt(capabilities.repositoryTools === true));
  }

  if (context.customInstructions) {
    sections.push(buildCustomInstructionsPrompt(context.customInstructions));
  }

  if (context.additionalDirectories?.length) {
    sections.push(
      buildAdditionalDirectoriesPrompt(context.additionalDirectories),
    );
  }

  if (context.additionalInstructions) {
    sections.push(context.additionalInstructions);
  }

  return sections.join("\n\n");
}

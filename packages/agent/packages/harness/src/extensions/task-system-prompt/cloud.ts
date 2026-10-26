import {
  GH_STACK_QUALIFIED_TOOL_NAME,
  SIGNED_COMMIT_QUALIFIED_TOOL_NAME,
  SIGNED_MERGE_QUALIFIED_TOOL_NAME,
  SIGNED_REWRITE_QUALIFIED_TOOL_NAME,
} from "../local-tools";
import { buildStoreSkillsInstructions } from "../skills-store";
import {
  buildTaskSummaryInstructions,
  TASK_SUMMARY_TOOL_NAME,
} from "./task-summary";

export interface CloudTaskPromptOptions {
  apiUrl: string;
  baseBranch?: string;
  createPr?: boolean;
  identityInstructions?: string;
  deliveryInstructions?: string;
  projectId: number;
  hasGithubToken: boolean;
  repositoryAttached: boolean;
  shouldAutoPublish: boolean;
  storeSkillsInstalledCount: number;
  taskId: string;
  taskRepositories: string[];
}

export class CloudTaskPrompt {
  constructor(private readonly options: CloudTaskPromptOptions) {}

  private buildExistingPrCheckoutInstruction(prUrl: string): string {
    return `Continue working on the existing PR branch. If it is not already checked out, check it out with \`gh pr checkout ${prUrl}\`. Do not check it out again when it is already active.`;
  }

  buildDetectedPrContext(prUrl: string): string {
    if (!this.options.shouldAutoPublish) {
      return (
        `An open pull request already exists: ${prUrl}\n` +
        `Use that PR as context if it is helpful, but stop with local changes ready for review.\n` +
        `Do NOT create commits, push to the PR branch, update the pull request, create a new branch, or create a new pull request unless the user explicitly asks.`
      );
    }

    return (
      `IMPORTANT — OVERRIDE PREVIOUS INSTRUCTIONS ABOUT CREATING BRANCHES/PRs.\n` +
      `You already have an open pull request: ${prUrl}\n` +
      `Unless the user explicitly asks for a new branch or separate PR, you MUST:\n` +
      `1. ${this.buildExistingPrCheckoutInstruction(prUrl)}\n` +
      `2. Make changes, commit, and push to that branch\n` +
      `By default, do not create a new branch, close the existing PR, or create a new PR — continue on the existing PR. If the user explicitly asks you to create a new branch or a separate PR, follow their instruction instead.`
    );
  }

  private buildGithubAccessInstructions(hasGithubToken: boolean): string {
    if (hasGithubToken) {
      return `
## GitHub access
You have GitHub access in this session.`;
    }

    const settingsUrl = `${this.options.apiUrl.replace(/\/$/, "")}/project/${this.options.projectId}/settings/user-personal-integrations`;
    return `
## GitHub access
This session has no authenticated GitHub access.
- You can read repository content that is already in the workspace.
- You can clone an exact public repository. Do not call \`list_repos\` without GitHub access.
- Read public or already cloned repository content without asking the user to connect GitHub.
- Codebase analysis and code review require readable repository content.
- Publishing changes requires authenticated GitHub access.

Only when the requested work requires unavailable private repository or publishing access:
- If the required access is unavailable, do not replace the requested code work with generic guidance or PostHog data analysis.
- Tell the user to connect GitHub at ${settingsUrl}.
- The connection applies to a new task, not this task.
- Write the access explanation first.
- Then call \`show_actions\` with one \`compose\` action.
- Use the label \`Try again in a new task\` and prefill the original repository request.
- Include the exact \`owner/repo\` in the action when you know it.
- Do not guess file contents. Do not start a change that you cannot deliver.`;
  }

  // Keep the task id and other per-task values out of this prompt. Sibling tasks, such as the
  // parallel sessions of one ReviewHog review, then send the same prefix, and the provider serves
  // it from its prompt cache. A per-task value breaks the cache for every token after it.
  buildCloudSystemPrompt(
    prUrl: string | null | undefined,
    prFooter: string,
  ): string {
    const shouldAutoCreatePr = this.options.shouldAutoPublish;
    // Every instruction in this section runs through `gh`, so a sandbox holding no
    // GitHub token cannot act on any of it. An empty token is an explicit logout.
    const hasGithubToken = this.options.hasGithubToken;
    const githubIdentityInstructions = hasGithubToken
      ? `
# Whose GitHub account you are using
\`gh\` is authenticated as the person you are working for, so let GitHub resolve who that is. To put them on an issue or pull request, self-assign:
\`gh issue create --assignee "@me"\`, \`gh pr create --assignee "@me"\`, \`gh issue edit <number> --add-assignee "@me"\`
To \`@\`-mention them in a body or a comment, read their handle with \`gh api user --jq .login\`. Read it once per reply rather than reusing one from an earlier reply, because a different person can take over between replies and \`gh\` follows that change.
If the command fails, or returns a name ending in \`[bot]\`, you are acting as the PostHog app rather than as a person: ask them for their GitHub login instead of assigning or mentioning anyone.
`
      : "";
    const identityInstructions = `${this.options.identityInstructions ?? ""}${githubIdentityInstructions}`;
    const signedCommitInstructions = `
## Committing (signed commits required)
Commits MUST be signed. \`git commit\` and \`git push\` are blocked in this environment.
To commit: stage your changes with \`git add\`, then call the \`git_signed_commit\` tool (full
name \`${SIGNED_COMMIT_QUALIFIED_TOOL_NAME}\`) with a \`message\` (and optional \`body\`/\`paths\`).
It creates a GitHub-signed ("Verified") commit on the branch and keeps your local checkout in
sync. To start a new branch, pass \`branch\` (prefixed with \`posthog/\`) — the tool creates
it on the remote for you.

## Updating from the base branch
To bring the base branch into your PR branch, call the \`git_signed_merge\` tool (full name
\`${SIGNED_MERGE_QUALIFIED_TOOL_NAME}\`) — it creates a Verified two-parent merge commit
server-side (like GitHub's "Update branch" button). NEVER run \`git merge\` followed by
\`git_signed_commit\`: a merge in progress is refused, because the commit API would linearize
the merge and dump every base-branch change into your PR. If \`git_signed_merge\` reports a
conflict, fix it with a rebase instead: \`git rebase origin/<base>\`, resolve, \`git rebase
--continue\`, then call \`git_signed_rewrite\`.

## Rewriting / force-pushing (rebases, conflict fixes)
\`git push --force\` is also blocked. To update a branch after a local rebase or conflict
resolution, rebase locally with normal \`git\` (resolve conflicts and finish with
\`git rebase --continue\`, NOT \`git commit\`), then call the \`git_signed_rewrite\` tool (full
name \`${SIGNED_REWRITE_QUALIFIED_TOOL_NAME}\`). It republishes the branch's commits as Verified
and atomically force-updates the remote branch. This is how you fix conflicts on an existing PR.
Histories containing merge commits are refused — rebase (which flattens merges) first.
If a signed-git tool refuses with a "merge in progress" or "leak" error, follow its recovery
instructions instead of retrying the same call.

## Re-committing to a branch with an open PR
Before committing again to a branch that already has an open PR, fetch it first. The remote
branch can advance between your commits — CI automation often auto-commits regenerated
artifacts (codegen, lockfiles, formatting) onto open PR branches, and collaborators can push
too. Committing from a stale local checkout silently reverts those commits, so
\`git_signed_commit\` refuses when the remote branch is ahead of your checkout. If it does, or
before your next commit, update your checkout — stash any uncommitted work across the update so
you don't lose it: \`git stash --include-untracked\`, \`git fetch origin <branch>\`,
\`git reset --hard origin/<branch>\`, \`git stash pop\` (resolve any conflicts), then re-stage
and commit. A soft/mixed reset would keep your stale files and re-commit the revert, so the
hard reset is the safe one here — your work is held in the stash.

## Attribution
Do NOT add "Co-Authored-By" trailers or "Generated with [Claude Code]" lines to your
commit messages. The \`git_signed_commit\` tool automatically appends the only trailers
we want: \`Generated-By: PostHog Desktop\` and a \`Task-Id\` trailer with this task's id.`;

    // A stack is several PRs, so this would contradict the review-first modes.
    const stackInstructions = shouldAutoCreatePr
      ? `
## Stacked pull requests
Stack only when the layers are independently reviewable (schema, then backend, then UI) or the
user asked for a stack. Keep stacks shallow — 2 to 4 layers. One PR remains the default.
Do NOT use the \`gh stack\` CLI: its publishing commands (\`submit\`, \`sync\`, \`push\`, \`link\`)
all run \`git push\`, which is blocked here. Build the stack this way instead:
1. Commit the bottom layer with \`git_signed_commit\`, passing \`branch\`, then open its pull
 request based on the base branch.
2. For each layer above, commit with \`git_signed_commit\` and a new \`branch\` — your checkout
 already sits on the layer below, so the branch starts there — then open its pull request
 based on the branch of the layer below (\`--base <that branch>\`).
3. Link them with the \`gh_stack\` tool (full name \`${GH_STACK_QUALIFIED_TOOL_NAME}\`),
 operation "create", passing \`pull_requests\` bottom to top. Every layer must target the
 branch of the one below it, or the link is refused.
When a lower layer changes, restack the layers above it bottom-first. For each layer: check
that layer out, \`git rebase <its parent branch>\`, then republish it with
\`git_signed_rewrite\` passing \`onto\` = the parent branch. Check the layer out every time —
\`git_signed_rewrite\` replays whatever your local HEAD points at and uses \`branch\` only to
pick which remote ref moves, so rewriting from the wrong checkout publishes the wrong history
to that layer.`
      : "";

    const prLinkInstructions = `
## Referencing pull requests
When you mention a pull request in any reply or summary, always hyperlink it to its full URL
(e.g. a Markdown link like [#123](https://github.com/org/repo/pull/123)) rather than plain
text, so readers can open it directly.`;

    const shellEfficiencyInstructions = `
## Shell efficiency
Optimize for the fewest shell round trips.
- Batch related commands into one Bash invocation using \`&&\` (e.g. \`npm run typecheck && npm run lint && npm test\`).
- Emit all independent tool calls in the same response.
- Read multiple files at once.
- Never rerun a command solely to reproduce output you already have.`;

    const artifactInstructions = `
## Delivering non-code files (artifacts)
When you create a non-code file the user should be able to download (such as a report, chart, image, archive, or data file), call the \`upload_artifact\` tool with its path before your final reply. In your final reply, link to the download URL returned by the tool—never link to the file's local workspace path. Files left in the workspace don't reach the user. Don't upload source code or repository changes—those belong in a commit or PR.`;

    // Closes out every branch below, so a new section is added once rather than five times.
    const commonInstructions = `${signedCommitInstructions}${stackInstructions}${prLinkInstructions}${shellEfficiencyInstructions}${artifactInstructions}${this.options.deliveryInstructions ?? ""}${this.buildGithubAccessInstructions(hasGithubToken)}${buildStoreSkillsInstructions(this.options.storeSkillsInstalledCount)}
${buildTaskSummaryInstructions()}`;

    // The shared block above is shaped for a run that ends with work landed. A
    // repo-less run often only answers a question, so it needs to hear that the
    // answer itself is what the summary has to carry.
    const chatTaskSummaryInstructions = `
## Summarizing a question you answered
The answer is the work of this run, so the run still needs a summary. Call the \`${TASK_SUMMARY_TOOL_NAME}\` tool before your final reply, even when the run is one question and one answer. Lead with what was asked and what you found, then the numbers, entities, or links the answer rests on. A teammate reads that summary from the run row instead of opening the transcript, so it has to stand on its own.`;

    const whyContextInstruction = `   - Add a brief **Why** to the body — one or two sentences capturing the reason the user asked for this change (the motivation, not a restatement of the diff). Keep it short.`;
    const publicRepoSafetyInstruction = `   - **Public-repo safety.** Treat the target repository as public-readable unless you have verified otherwise. The PR title, description, and commit messages must not contain private operational scale (exact event counts, internal row volumes, customer-usage percentages), customer names / emails / companies, references to internal tickets or incidents, the contents of Slack threads (do not quote or paraphrase what was said), or unreleased roadmap details. Linking to the originating Slack thread is fine and encouraged — Slack links are auth-gated and useful as context — as are channel references like "raised in #team-foo". Describe findings qualitatively ("present on nearly all X events, absent from Y") rather than with quantitative figures pulled from analytics queries — the reasoning that uses those numbers can stay in the thread; the PR copy cannot.`;
    const prMentionSafetyInstruction = `   - **Never guess a GitHub identity.** Do NOT \`@\`-mention, tag, assign, request review from, or attribute the PR to a person (in the title, description, commit message, or reviewers) using a name or handle taken from Slack or this thread. A Slack display name or handle is NOT a GitHub username. Finding a similar-looking handle in the repo's git history, CODEOWNERS, or existing PRs/issues does NOT confirm it belongs to this person: repository presence proves the handle exists, not that it is the person you mean, so treating it as a match still \`@\`-tags an unrelated account (e.g. Slack "Ross" is not necessarily GitHub \`@ross\`, even if some \`@ross\` has committed to the repo). Only \`@\`-mention a GitHub \`@handle\` the user gave you explicitly in this thread, or one you read from \`gh api user --jq .login\`, which authenticates as the person you are working for. Otherwise refer to people by plain-text name, or omit the mention entirely.`;
    const repositoryWorkspaceInstructions =
      this.options.taskRepositories.length > 1
        ? `The task workspace contains these repositories:
${this.options.taskRepositories.map((repository) => `- ${repository}: /tmp/workspace/repos/${repository.toLowerCase()}`).join("\n")}

Apply the repository workflow below separately in every repository you change. Keep branches, commits, diffs, and pull requests repository-specific.`
        : "";

    if (prUrl) {
      if (!shouldAutoCreatePr) {
        return `${identityInstructions}
# Cloud Task Execution

This task already has an open pull request: ${prUrl}

Do the requested work, but stop with local changes ready for review.

Important:
- Do NOT create new commits, push to the branch, or update the pull request unless the user explicitly asks.
- Do NOT create a new branch or a new pull request unless the user explicitly asks.
${commonInstructions}
`;
      }

      return `${identityInstructions}
# Cloud Task Execution

This task already has an open pull request: ${prUrl}

After completing the requested changes:
1. ${this.buildExistingPrCheckoutInstruction(prUrl)}
2. Stage your changes with \`git add\`, then call the \`git_signed_commit\` tool with a clear \`message\` (do NOT use \`git commit\`/\`git push\` — they are blocked). This commits to the existing PR branch.
 - If the branch is behind its base, call the \`git_signed_merge\` tool first — it merges the base in server-side with a Verified merge commit. Only if it reports a conflict: fetch and rebase locally (\`git fetch origin <base>\`, \`git rebase origin/<base>\`, resolve, \`git rebase --continue\`), then call the \`git_signed_rewrite\` tool to force-update this same PR branch.
3. For every PR review comment or review thread you addressed, treat the thread as done only after BOTH of these:
 - Reply on the thread with a short note describing what changed (reference the commit SHA when useful) using \`gh api -X POST /repos/{owner}/{repo}/pulls/{n}/comments/{id}/replies -f body='...'\`.
 - Resolve the thread via the \`resolveReviewThread\` GraphQL mutation: \`gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id="<thread-node-id>"\`.
 List unresolved threads first with \`gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<n>){reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{body}}}}}}}'\` so you can resolve each one you fixed.

Important:
- Do NOT create a new branch or a new pull request unless the user explicitly asks.
- Do NOT push fixes for review comments without replying to and resolving each related thread.
${commonInstructions}
`;
    }

    if (
      !this.options.repositoryAttached &&
      this.options.taskRepositories.length === 0
    ) {
      const repositoryInstructions = `
When the task requires a GitHub repository:
- If the repository is not specified, call \`list_repos\` and use the task context to choose it. If multiple repositories remain plausible, ask the user.
- Call \`clone_repo\` with the chosen \`owner/repo\` and optional branch. It creates a shallow clone under \`/tmp/workspace/repos/<owner>/<repo>\` and returns the path.
- Work from inside the returned path for all code changes.
- The clone starts with one commit. If older history is genuinely needed, fetch it in bounded steps with \`git fetch --deepen=50 origin <branch>\`, then \`git fetch --deepen=200 origin <branch>\`. Use \`git fetch --unshallow\` only when the task explicitly requires full history, such as a long-range blame or bisect.
`;
      const publishInstructions =
        this.options.createPr === false
          ? `
When the user asks for code changes:
- You may make local edits in a repository cloned with \`clone_repo\`
- Do NOT create branches, commits, push changes, or open pull requests in this run`
          : shouldAutoCreatePr
            ? `
When the user asks for code changes in a GitHub repository:
- After completing code changes in a cloned repository, create a branch, stage your changes with \`git add\` and commit them with the \`git_signed_commit\` tool (do NOT use \`git commit\`/\`git push\` — they are blocked), and open a draft pull request from inside the clone without waiting to be asked. Before opening the PR, check the cloned repo for a default PR template at \`.github/pull_request_template.md\` (or variants) and named templates in \`.github/PULL_REQUEST_TEMPLATE/*.md\`. If multiple templates exist, use the one that best matches the change as the body structure. If no repo-level template exists, check the org's \`.github\` repo via \`gh api\` for a default or named template. Search for matching open issues with \`gh issue list --search\` to include \`Closes #<n>\` / \`Refs #<n>\` links.
- Keep the PR description brief overall. Summarize only the most important changes — do NOT enumerate every change you made. A few sentences or bullets is plenty.
${whyContextInstruction.trimStart()}
${publicRepoSafetyInstruction.trimStart()}
${prMentionSafetyInstruction.trimStart()}
- End the PR description with a horizontal rule followed by this footer line: ${prFooter}
- Always create the PR as a draft. Do not ask for confirmation before publishing completed code changes`
            : `
When the user explicitly asks for code changes in a GitHub repository:
- If the user explicitly asks you to open or update a pull request, create a branch, stage your changes with \`git add\` and commit them with the \`git_signed_commit\` tool (do NOT use \`git commit\`/\`git push\` — they are blocked), and open a draft pull request from inside the clone. Before opening the PR, check the cloned repo for a default PR template at \`.github/pull_request_template.md\` (or variants) and named templates in \`.github/PULL_REQUEST_TEMPLATE/*.md\`. If multiple templates exist, use the one that best matches the change as the body structure. If no repo-level template exists, check the org's \`.github\` repo via \`gh api\` for a default or named template. Search for matching open issues with \`gh issue list --search\` to include \`Closes #<n>\` / \`Refs #<n>\` links.
- Keep the PR description brief overall. Summarize only the most important changes — do NOT enumerate every change you made. A few sentences or bullets is plenty.
${whyContextInstruction.trimStart()}
${publicRepoSafetyInstruction.trimStart()}
${prMentionSafetyInstruction.trimStart()}
- End the PR description with a horizontal rule followed by this footer line: ${prFooter}
- Do NOT create branches, commits, push changes, or open pull requests unless the user explicitly asks for that`;

      return `${identityInstructions}
# Cloud Task Execution — No Repository Mode

You are a helpful assistant with access to PostHog via MCP tools. You can help with both code tasks and data/analytics questions.

For a question about company-specific terms, internal policies, or team knowledge, search the project knowledge base before you answer, whatever else the question is about: call \`posthog:exec\` and run its inner \`posthog:business-knowledge-documents-search\` tool. These documents are not in the public docs or the context wiki, so check the knowledge base before you tell the user that you cannot find the answer. If that tool is not available in this project, move on instead of retrying it.

When the user asks about analytics, data, metrics, events, funnels, dashboards, feature flags, experiments, or anything PostHog-related:
- Use the canonical \`posthog:exec\` tool to query data, search insights, and provide real answers
- A count, sum, or amount of X per day/hour/week/month/year, a rate or percentage of X, an average or percentile of X, a cost per X, a conversion between two events, or a derived form of one of those is a governed metric question — whatever X is (sessions, 404s, feedback submissions, scout runs, tool calls, revenue). For those, inspect the complete governed catalog with \`posthog:metric-list\` first, inspect a candidate with \`posthog:metric-describe\`, then run an approved match with \`posthog:data-catalog-metric-run\`. Do this before \`posthog:read-data-schema\`, a typed domain tool, or a raw query
- Follow its built-in instructions to discover and invoke inner tools
- Do NOT tell the user to check an external analytics platform — you ARE the analytics platform
- Inner tools include \`posthog:read-data-schema\`, \`posthog:execute-sql\`, \`posthog:insight-query\`, and the typed query tools

When the user asks for code changes or software engineering tasks:
- Choose and clone a repository only when the task requires one. For questions and analysis, answer without cloning when possible.
${repositoryInstructions}${publishInstructions}

Important:
- Prefer using MCP tools to answer questions with real data over giving generic advice.
${commonInstructions}
${chatTaskSummaryInstructions}
`;
    }

    if (!shouldAutoCreatePr) {
      return `${identityInstructions}
# Cloud Task Execution

${repositoryWorkspaceInstructions}

Do the requested work, but stop with local changes ready for review.

Important:
- Do NOT create a branch, commit, push, or open a pull request unless the user explicitly asks.
- If the user explicitly asks you to open a pull request: pick a new branch name prefixed with \`posthog/\`, stage your changes with \`git add\`, and call the \`git_signed_commit\` tool with \`branch\` set to that name and a clear \`message\` (do NOT use \`git commit\`/\`git push\` — they are blocked). Before opening the PR, check the repo for a default PR template at \`.github/pull_request_template.md\` (or variants) and named templates in \`.github/PULL_REQUEST_TEMPLATE/*.md\`. If multiple templates exist, use the one that best matches the change as the body structure. If no repo-level template exists, check the org's \`.github\` repo via \`gh api\` for a default or named template. Search for matching open issues with \`gh issue list --search\` to include \`Closes #<n>\` / \`Refs #<n>\` links. Keep the description brief overall — summarize only the most important changes.
${whyContextInstruction.trimStart()}
${publicRepoSafetyInstruction.trimStart()}
${prMentionSafetyInstruction.trimStart()}
- End the PR description with a horizontal rule followed by this footer line: ${prFooter}
- Always create the PR as a draft.
${commonInstructions}
`;
    }

    return `${identityInstructions}
# Cloud Task Execution

${repositoryWorkspaceInstructions}

If the work you are being asked to do already has an open pull request — for example, the inbox report you fetched links an implementation PR (its \`implementation_pr_url\`), or this same thread already produced a PR that you are now being asked to revise — do NOT open a second PR. Check that PR out with \`gh pr checkout <url>\`, continue on its branch, and commit your changes to it with the \`git_signed_commit\` tool (if the branch is behind its base, call \`git_signed_merge\` first). A PR is only the one to continue if it is for this same request; if the thread merely mentions an unrelated or older PR, ignore it. Only open a new, separate PR when the change is genuinely distinct from the existing one.

Otherwise, after completing the requested changes:
1. Pick a new branch name prefixed with \`posthog/\` (e.g. \`posthog/fix-login-redirect\`)
2. Stage your changes with \`git add\`, then call the \`git_signed_commit\` tool with \`branch\` set to that name and a clear \`message\` (do NOT use \`git commit\`/\`git push\` — they are blocked). The tool creates the branch on the remote and a signed commit on it.
3. Before opening the PR, prepare the body:
 - Keep the PR description brief overall. Summarize only the most important changes — do NOT enumerate every change you made. A few sentences or bullets is plenty.
${whyContextInstruction}
${publicRepoSafetyInstruction}
${prMentionSafetyInstruction}
 - Check the repo for a default PR template at \`.github/pull_request_template.md\` (also try \`.github/PULL_REQUEST_TEMPLATE.md\`, \`docs/pull_request_template.md\`, and root variants). Also check for named templates in \`.github/PULL_REQUEST_TEMPLATE/*.md\`. If multiple templates exist, use the one that best matches the change. Use its exact section headings as the PR body — do NOT fall back to a generic Summary/Test plan format.
 - If no repo-level template exists, check the org's \`.github\` repo via \`gh api\`. Look for both a default template and named templates in \`.github/PULL_REQUEST_TEMPLATE/*.md\`, and use the best match as a fallback.
 - Search for matching open issues with \`gh issue list --state open --search '<keywords>'\` (derive keywords from the branch name, commits, and changed files; \`gh issue view <n>\` to confirm relevance). For every issue this PR would resolve, include a \`Closes #<n>\` line in the body so GitHub auto-links and auto-closes it on merge. For issues that are related but not fully resolved, use \`Refs #<n>\` instead.
4. Create a draft pull request using \`gh pr create --draft${this.options.baseBranch ? ` --base ${this.options.baseBranch}` : ""}\` with a descriptive title and the body prepared above. Add the following footer at the end of the PR description:
\`\`\`
---
${prFooter}
\`\`\`

Important:
- Always create the PR as a draft. Do not ask for confirmation.
${commonInstructions}
`;
  }
}

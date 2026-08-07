import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import { LLM_GATEWAY_SERVICE } from "../llm-gateway/identifiers";
import {
  HELPER_GATEWAY_MODEL,
  type LlmGatewayService,
} from "../llm-gateway/llm-gateway";
import { CreatePrSaga, type CreatePrStep } from "./create-pr-saga";
import {
  type CreatePrHost,
  type CreatePrInput,
  type CreatePrResult,
  GIT_DIFF_SOURCE,
  type GitDiffSource,
  type GitPrLogger,
} from "./identifiers";

const MAX_DIFF_LENGTH = 8000;

@injectable()
export class GitPrService {
  private readonly log: GitPrLogger;

  constructor(
    @inject(GIT_DIFF_SOURCE)
    private readonly gitDiff: GitDiffSource,
    @inject(LLM_GATEWAY_SERVICE)
    private readonly llm: LlmGatewayService,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.log = logger.scope("git-pr");
  }

  async generateCommitMessage(
    directoryPath: string,
    conversationContext?: string,
  ): Promise<{ message: string }> {
    const [stagedDiff, unstagedDiff, conventions, changedFiles] =
      await Promise.all([
        this.gitDiff.getStagedDiff(directoryPath),
        this.gitDiff.getUnstagedDiff(directoryPath),
        this.gitDiff.getCommitConventions(directoryPath),
        this.gitDiff.getChangedFilesHead(directoryPath),
      ]);

    const diff = stagedDiff || unstagedDiff;
    if (!diff && changedFiles.length === 0) {
      return { message: "" };
    }

    const truncatedDiff =
      diff.length > MAX_DIFF_LENGTH
        ? `${diff.slice(0, MAX_DIFF_LENGTH)}\n... (diff truncated)`
        : diff;

    const filesSummary = changedFiles
      .map((f) => `${f.status}: ${f.path}`)
      .join("\n");

    const conventionHint = conventions.conventionalCommits
      ? `This repository uses conventional commits. Common prefixes: ${
          conventions.commonPrefixes.join(", ") || "feat, fix, docs, chore"
        }.
Example messages from this repo:
${conventions.sampleMessages.slice(0, 3).join("\n")}`
      : `Example messages from this repo:
${conventions.sampleMessages.slice(0, 3).join("\n")}`;

    const system = `You are a git commit message generator. Generate a concise, descriptive commit message for the given changes.

${conventionHint}

Rules:
- First line should be a short summary (max 72 chars)
- Use imperative mood ("Add feature" not "Added feature")
- Be specific about what changed
- If using conventional commits, include the appropriate prefix
- If conversation context is provided, use it to understand WHY the changes were made and reflect that intent
- Do not include any explanation, just output the commit message`;

    const contextSection = conversationContext
      ? `\n\nConversation context (why these changes were made):\n${conversationContext}`
      : "";

    const userMessage = `Generate a commit message for these changes:

Changed files:
${filesSummary}

Diff:
${truncatedDiff}${contextSection}`;

    this.log.debug("Generating commit message", {
      fileCount: changedFiles.length,
      diffLength: diff.length,
      conventionalCommits: conventions.conventionalCommits,
      hasConversationContext: !!conversationContext,
    });

    const response = await this.llm.prompt(
      [{ role: "user", content: userMessage }],
      {
        system,
        model: HELPER_GATEWAY_MODEL,
        posthogProperties: { $ai_span_name: "commit_message" },
      },
    );

    return { message: response.content.trim() };
  }

  async generatePrTitleAndBody(
    directoryPath: string,
    conversationContext?: string,
  ): Promise<{ title: string; body: string }> {
    await this.gitDiff.fetchFromRemote(directoryPath);

    const [defaultBranch, currentBranch, prTemplate] = await Promise.all([
      this.gitDiff.getDefaultBranch(directoryPath),
      this.gitDiff.getCurrentBranch(directoryPath),
      this.gitDiff.getPrTemplate(directoryPath),
    ]);

    const head = currentBranch ?? undefined;
    const [branchDiff, stagedDiff, unstagedDiff, commits, conventions] =
      await Promise.all([
        this.gitDiff.getDiffAgainstRemote(directoryPath, defaultBranch),
        this.gitDiff.getStagedDiff(directoryPath),
        this.gitDiff.getUnstagedDiff(directoryPath),
        this.gitDiff.getCommitsBetweenBranches(
          directoryPath,
          defaultBranch,
          head,
          30,
        ),
        this.gitDiff.getCommitConventions(directoryPath),
      ]);

    const uncommittedDiff = [stagedDiff, unstagedDiff]
      .filter(Boolean)
      .join("\n");
    const parts = [branchDiff, uncommittedDiff].filter(Boolean);
    const fullDiff = parts.join("\n");
    if (commits.length === 0 && !fullDiff) {
      return { title: "", body: "" };
    }
    const commitsSummary = commits.map((c) => `- ${c.message}`).join("\n");
    const truncatedDiff = fullDiff
      ? fullDiff.length > MAX_DIFF_LENGTH
        ? `${fullDiff.slice(0, MAX_DIFF_LENGTH)}\n... (diff truncated)`
        : fullDiff
      : "";

    const templateHint = prTemplate.template
      ? `The repository has a PR template. Use it as a guide for structure but adapt the content to match the actual changes:\n${prTemplate.template.slice(
          0,
          2000,
        )}`
      : "";

    const conventionHint = conventions.conventionalCommits
      ? `- Use conventional commit format for the title (e.g., "feat(scope): description"). Common prefixes: ${
          conventions.commonPrefixes.join(", ") || "feat, fix, docs, chore"
        }.`
      : "";

    const system = `You are a PR description generator. Generate a title and detailed description for a pull request.

Output format (use exactly this format):
TITLE: <short descriptive title, max 72 chars>

BODY:
<detailed description>

Rules for the title:
- Short and descriptive (max 72 chars)
- Use imperative mood ("Add feature" not "Added feature")
- Be specific about what the PR accomplishes
${conventionHint}

Rules for the body:
- Start with a TL;DR section (1-2 sentences summarizing the change)
- Include a "What changed?" section with bullet points describing the key changes
- If conversation context is provided, use it to explain WHY the changes were made in the TL;DR
- Be thorough but concise
- Use markdown formatting
- Only describe changes that are actually in the diff — do not invent or assume changes
- Treat the target repository as public-readable. Do not include private operational scale (exact event counts, internal row volumes, customer-usage percentages), customer names / emails / companies, references to internal tickets or incidents, or the contents of Slack threads (do not quote or paraphrase what was said) — describe findings qualitatively instead. Linking to the originating Slack thread is fine and encouraged, as are channel references like "raised in #team-foo" — Slack links are auth-gated and useful as context.
${templateHint}

Do not include any explanation outside the TITLE and BODY sections.`;

    const contextSection = conversationContext
      ? `\n\nConversation context (why these changes were made):\n${conversationContext}`
      : "";

    const userMessage = `Generate a PR title and description for these changes:

Branch: ${currentBranch ?? "unknown"} -> ${defaultBranch}

Commits in this PR:
${commitsSummary || "(no commits yet - changes are uncommitted)"}

Diff:
${truncatedDiff || "(no diff available)"}${contextSection}`;

    this.log.debug("Generating PR title and body", {
      commitCount: commits.length,
      diffLength: fullDiff.length,
      hasTemplate: !!prTemplate.template,
      hasConversationContext: !!conversationContext,
      conventionalCommits: conventions.conventionalCommits,
    });

    const response = await this.llm.prompt(
      [{ role: "user", content: userMessage }],
      {
        system,
        maxTokens: 2000,
        model: HELPER_GATEWAY_MODEL,
        posthogProperties: { $ai_span_name: "pr_description" },
      },
    );

    const content = response.content.trim();
    const titleMatch = content.match(/^TITLE:\s*(.+?)(?:\n|$)/m);
    const bodyMatch = content.match(/BODY:\s*([\s\S]+)$/m);

    return {
      title: titleMatch?.[1]?.trim() ?? "",
      body: bodyMatch?.[1]?.trim() ?? "",
    };
  }

  async generatePrShortSummary(
    conversationContext?: string,
    prTitle?: string,
  ): Promise<{ summary: string }> {
    if (!conversationContext && !prTitle) return { summary: "" };

    const system = `You generate ultra-short labels for pull requests. Given context about a PR, output a label of 15-20 characters that captures what the PR does.

Rules:
- 15-20 characters total, never more than 24
- Plain words, no punctuation, no quotes, no trailing period
- Imperative mood ("Fix login loop" not "Fixed login loop")
- Output only the label, nothing else`;

    const parts: string[] = [];
    if (prTitle) parts.push(`PR title: ${prTitle}`);
    if (conversationContext) {
      parts.push(`Conversation context:\n${conversationContext}`);
    }

    const response = await this.llm.prompt(
      [{ role: "user", content: parts.join("\n\n") }],
      {
        system,
        maxTokens: 30,
        model: HELPER_GATEWAY_MODEL,
        posthogProperties: { $ai_span_name: "pr_short_summary" },
      },
    );

    const summary = response.content.trim().replace(/^["']|["']$/g, "");
    return { summary: summary.length > 24 ? summary.slice(0, 24) : summary };
  }

  /**
   * Orchestrate branch -> commit -> push -> PR creation as a saga. Host git/gh
   * operations come through `host`; commit-message and PR-description generation
   * reuse this service's own LLM-backed methods. Progress is reported through
   * `onProgress` so the host can stream it to the renderer.
   */
  async createPr(
    input: CreatePrInput,
    host: CreatePrHost,
    onProgress: (step: CreatePrStep, message: string, prUrl?: string) => void,
  ): Promise<CreatePrResult> {
    const { directoryPath } = input;
    const sessionEnv = await host.getSessionEnvForTask(input.taskId);

    const saga = new CreatePrSaga(
      {
        getCurrentBranch: (dir) => host.getCurrentBranch(dir),
        createBranch: (dir, name) => host.createBranch(dir, name),
        getChangedFilesHead: (dir) => host.getChangedFilesHead(dir),
        generateCommitMessage: (dir) =>
          this.generateCommitMessage(dir, input.conversationContext),
        getHeadSha: (dir) => host.getHeadSha(dir),
        commit: (dir, message, options) =>
          host.commit(dir, message, { ...options, env: sessionEnv }),
        resetSoft: (dir, sha) => host.resetSoft(dir, sha),
        getSyncStatus: (dir) => host.getSyncStatus(dir),
        push: (dir) => host.push(dir, sessionEnv),
        publish: (dir) => host.publish(dir, sessionEnv),
        generatePrTitleAndBody: (dir) =>
          this.generatePrTitleAndBody(dir, input.conversationContext),
        createPr: (dir, title, body, draft) =>
          host.createPrViaGh(dir, title, body, draft, sessionEnv),
        onProgress,
      },
      this.log,
    );

    const result = await saga.run({
      directoryPath,
      branchName: input.branchName,
      commitMessage: input.commitMessage,
      prTitle: input.prTitle,
      prBody: input.prBody,
      draft: input.draft,
      stagedOnly: input.stagedOnly,
      taskId: input.taskId,
    });

    if (!result.success) {
      onProgress("error", result.error);
      return {
        success: false,
        message: result.error,
        prUrl: null,
        failedStep: result.failedStep,
      };
    }

    const state = await host.getPrState(directoryPath);

    if (input.taskId) {
      const linkedBranch =
        input.branchName ?? (await host.getCurrentBranch(directoryPath));
      if (linkedBranch) {
        host.linkBranch(input.taskId, linkedBranch, "user");
      }
    }

    onProgress(
      "complete",
      "Pull request created",
      result.data.prUrl ?? undefined,
    );

    return {
      success: true,
      message: "Pull request created",
      prUrl: result.data.prUrl,
      failedStep: null,
      state,
    };
  }
}

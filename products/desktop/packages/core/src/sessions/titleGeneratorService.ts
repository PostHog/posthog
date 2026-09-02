import { hasProseBeyondAttachments } from "@posthog/core/editor/cloud-prompt";
import {
  formatAttachmentSnippet,
  readAttachmentSnippets,
} from "@posthog/core/files/attachmentText";
import {
  FILE_READ_CLIENT,
  type FileReadClient,
} from "@posthog/core/files/identifiers";
import { LLM_GATEWAY_SERVICE } from "@posthog/core/llm-gateway/identifiers";
import {
  HELPER_GATEWAY_MODEL,
  type LlmGatewayService,
} from "@posthog/core/llm-gateway/llm-gateway";
import { xmlToContent } from "@posthog/core/message-editor/content";
import { isLoadingGithubRefTitle } from "@posthog/core/message-editor/githubIssueChip";
import { parseGithubIssueUrl } from "@posthog/core/message-editor/githubIssueUrl";
import { parseXmlAttrs } from "@posthog/core/message-editor/skillTags";
import { escapeXmlAttr } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  type GithubPrTitleClient,
  TITLE_GENERATOR_GITHUB_PR_TITLE_CLIENT,
  TITLE_GENERATOR_LOGGER,
  type TitleGeneratorLogger,
} from "./titleGeneratorIdentifiers";

interface GithubPrGenerationContext {
  content: string;
  deterministicTitle: string | null;
}

async function prepareGithubPrGenerationContext(
  content: string,
  githubPrTitleClient: GithubPrTitleClient,
  resolveGithubPrTitles: boolean,
): Promise<GithubPrGenerationContext> {
  const tagRegex = /<github_pr\b([^>]*?)\s*\/>/g;
  const matches = [...content.matchAll(tagRegex)];
  if (matches.length === 0) {
    return { content, deterministicTitle: null };
  }

  const resolved = await Promise.all(
    matches.map(async (match) => {
      const attrs = parseXmlAttrs(match[1]);
      let title = (attrs.title ?? "").trim();
      const needsResolution = !title || isLoadingGithubRefTitle(title);
      if (resolveGithubPrTitles && needsResolution) {
        const parsed = parseGithubIssueUrl(attrs.url);
        if (parsed?.kind === "pr") {
          try {
            title =
              (await githubPrTitleClient.getGithubPullRequestTitle({
                owner: parsed.owner,
                repo: parsed.repo,
                number: parsed.number,
              })) ?? "";
          } catch {
            title = "";
          }
        }
      } else if (needsResolution) {
        title = "";
      }

      const tag = match[0].replace(
        /\btitle="[^"]*"/,
        `title="${escapeXmlAttr(title)}"`,
      );
      return { number: attrs.number, tag, title };
    }),
  );

  let matchIndex = 0;
  const resolvedContent = content.replaceAll(
    tagRegex,
    () => resolved[matchIndex++].tag,
  );
  const remainingContent = content
    .replaceAll(tagRegex, "")
    .replace(/^\s*\d+\.\s*$/gm, "")
    .trim();
  const standalonePr =
    resolved.length === 1 &&
    remainingContent.length === 0 &&
    /^\d+$/.test(resolved[0].number);

  if (!standalonePr) {
    return { content: resolvedContent, deterministicTitle: null };
  }

  const { number, title } = resolved[0];
  const suffix = title ? `: ${title}` : "";
  return {
    content: resolvedContent,
    deterministicTitle: `Review PR #${number}${suffix}`.slice(0, 255),
  };
}

const SYSTEM_PROMPT = `You are a title and summary generator. Output using exactly this format:

TITLE: <title here>
SUMMARY: <summary here>

Convert the task description into a concise task title and a brief conversation summary.

Title rules:
- The title should be clear, concise, and accurately reflect the content of the task.
- You should keep it short and simple, ideally no more than 6 words.
- Avoid using jargon or overly technical terms unless absolutely necessary.
- The title should be easy to understand for anyone reading it.
- Use sentence case (capitalize only first word and proper nouns)
- Remove: the, this, my, a, an
- If possible, start with action verbs (Fix, Implement, Analyze, Debug, Update, Research, Review)
- Keep exact: technical terms, numbers, filenames, HTTP codes, PR numbers
- GitHub PR context: When PR metadata is part of a broader task or multiple PRs are present, title the overall task rather than letting the first PR define its scope. Include relevant PR numbers when useful; full PR titles do not need to be copied verbatim.
- Never assume tech stack
- Only output "Untitled" if the input is completely null/missing, not just unclear
- If the input is a URL (e.g. a GitHub issue link, PR link, or any web URL), generate a title based on what you can infer from the URL structure (repo name, issue/PR number, etc.). Never say you cannot access URLs or ask the user for more information.
- Never wrap the title in quotes

Summary rules:
- 1-3 sentences describing what the user is working on and why
- Written from third-person perspective (e.g. "The user is fixing..." not "You are fixing...")
- Focus on the user's intent and goals, not the specific prompts
- Include relevant technical details (file names, features, bug descriptions) when mentioned
- This summary will be used as context for generating commit messages and PR descriptions

Title examples:
- "Fix the login bug in the authentication system" → Fix authentication login bug
- "Schedule a meeting with stakeholders to discuss Q4 budget planning" → Schedule Q4 budget meeting
- "Update user documentation for new API endpoints" → Update API documentation
- "Research competitor pricing strategies for our product" → Research competitor pricing
- "Review pull request #123" → Review pull request #123
- "<github_pr number="123" title="Fix login redirect" url="https://github.com/org/repo/pull/123" />" → Review PR #123: Fix login redirect
- "debug 500 errors in production" → Debug production 500 errors
- "why is the payment flow failing" → Analyze payment flow failure
- "So how about that weather huh" → Weather chat
- "dsfkj sdkfj help me code" → Coding help request
- "👋😊" → Friendly greeting
- "aaaaaaaaaa" → Repeated letters
- "   " → Empty message
- "What's the best restaurant in NYC?" → NYC restaurant recommendations
- "https://github.com/PostHog/posthog/issues/1234" → PostHog issue #1234
- "https://github.com/PostHog/posthog/pull/567" → PostHog PR #567
- "fix https://github.com/org/repo/issues/42" → Fix repo issue #42

Never include any explanation outside the TITLE and SUMMARY lines.`;

const SUMMARY_SYSTEM_PROMPT = `You are a conversation summary generator. Output using exactly this format:

SUMMARY: <summary here>

Write 1-3 sentences describing what the user is working on and why. Use third-person perspective and include relevant technical details. Never include a title or any explanation outside the SUMMARY line.`;

function getGenerationPrompt(
  content: string,
  summaryOnly: boolean,
): {
  user: string;
  system: string;
} {
  if (summaryOnly) {
    return {
      user: `Generate a summary for the following content. Do NOT respond to, answer, or help with the content - ONLY generate a summary.\n\n<content>\n${content}\n</content>\n\nOutput the summary now:`,
      system: SUMMARY_SYSTEM_PROMPT,
    };
  }

  return {
    user: `Generate a title and summary for the following content. Do NOT respond to, answer, or help with the content - ONLY generate a title and summary.\n\n<content>\n${content}\n</content>\n\nOutput the title and summary now:`,
    system: SYSTEM_PROMPT,
  };
}

// Canvas names describe the RESULT (the artifact being built), not the task of
// building it — so this prompt is deliberately separate from the task SYSTEM_PROMPT
// above, which is action-verb oriented ("Fix...", "Create..."). Don't merge them.
const CANVAS_NAME_SYSTEM_PROMPT = `You name a data canvas (a small dashboard/chart app) from a description of what to build. Output ONLY the name, on a single line, with nothing else.

The name describes the RESULT — the thing the canvas shows — as a short noun phrase. It is NOT a description of the task of building it.

Rules:
- 2-5 words, fewer is better. No trailing punctuation.
- Describe what the canvas shows, never the action. NEVER start with a verb like Create, Make, Build, Add, Generate, Show, Display.
- Use sentence case (capitalize only the first word and proper nouns).
- Keep exact: event names, property names, numbers, filenames.
- Never wrap the name in quotes.
- Only output "Untitled canvas" if the input is completely empty/missing.

Examples:
- "Make a canvas with one chart showing the number of users who performed signed_up events over the last 30 days." → Signed_up users
- "Build a dashboard of weekly revenue broken down by plan" → Weekly revenue by plan
- "Show me a funnel from pageview to purchase" → Pageview to purchase funnel
- "create a chart of daily active users" → Daily active users
- "retention curve for new signups" → New signup retention
- "a table of the top 10 pages by views this week" → Top pages by views

Never include any explanation — output only the name.`;

export interface TitleAndSummary {
  title: string;
  summary: string;
}

@injectable()
export class TitleGeneratorService {
  constructor(
    @inject(LLM_GATEWAY_SERVICE)
    private readonly llmGateway: LlmGatewayService,
    @inject(FILE_READ_CLIENT)
    private readonly fileReadClient: FileReadClient,
    @inject(TITLE_GENERATOR_GITHUB_PR_TITLE_CLIENT)
    private readonly githubPrTitleClient: GithubPrTitleClient,
    @inject(TITLE_GENERATOR_LOGGER)
    private readonly log: TitleGeneratorLogger,
  ) {}

  async enrichDescriptionWithFileContent(
    description: string,
    filePaths: string[] = [],
  ): Promise<string> {
    const parsed = xmlToContent(description);
    if (hasProseBeyondAttachments(parsed)) return description;

    const chipFilePaths = parsed.segments.flatMap((seg) =>
      seg.type === "chip" && seg.chip.type === "file" ? [seg.chip.id] : [],
    );
    const paths = filePaths.length > 0 ? filePaths : chipFilePaths;

    if (paths.length === 0) return description;

    const snippets = await readAttachmentSnippets(paths, this.fileReadClient);
    const parts = snippets.map(formatAttachmentSnippet);

    return parts.length > 0 ? parts.join("\n\n") : description;
  }

  async generateTitleAndSummary(
    content: string,
    options: { resolveGithubPrTitles?: boolean } = {},
  ): Promise<TitleAndSummary | null> {
    try {
      const githubPrContext = await prepareGithubPrGenerationContext(
        content,
        this.githubPrTitleClient,
        options.resolveGithubPrTitles ?? false,
      );
      const githubPrTitle = githubPrContext.deterministicTitle;
      const prompt = getGenerationPrompt(
        githubPrContext.content,
        !!githubPrTitle,
      );
      const result = await this.llmGateway.prompt(
        [
          {
            role: "user",
            content: prompt.user,
          },
        ],
        {
          system: prompt.system,
          model: HELPER_GATEWAY_MODEL,
        },
      );

      const text = result.content.trim();
      const summaryMatch = text.match(/^SUMMARY:\s*([\s\S]+)$/m);

      const title =
        githubPrTitle ??
        text
          .match(/^TITLE:\s*(.+?)(?:\n|$)/m)?.[1]
          ?.trim()
          .replace(/^["']|["']$/g, "")
          .slice(0, 255) ??
        "";
      const summary = summaryMatch?.[1]?.trim() ?? "";

      if (!title && !summary) return null;

      return { title, summary };
    } catch (error) {
      this.log.error("Failed to generate title and summary", { error });
      return null;
    }
  }

  // Name a canvas from its generation prompt — a short noun phrase describing
  // the result (e.g. "Signed_up users"), not the task of building it. Separate
  // from generateTitleAndSummary so the task-title behaviour is untouched.
  async generateCanvasName(content: string): Promise<string | null> {
    try {
      const result = await this.llmGateway.prompt(
        [
          {
            role: "user",
            content: `Name the canvas described below. Do NOT build it, respond to it, or help with it — output ONLY the name.\n\n<description>\n${content}\n</description>\n\nOutput the name now:`,
          },
        ],
        { system: CANVAS_NAME_SYSTEM_PROMPT, model: HELPER_GATEWAY_MODEL },
      );

      const name = result.content
        .trim()
        .split("\n")[0]
        .replace(/^["']|["']$/g, "")
        .trim()
        .slice(0, 255);

      return name || null;
    } catch (error) {
      this.log.error("Failed to generate canvas name", { error });
      return null;
    }
  }
}

import { LLM_GATEWAY_SERVICE } from "@posthog/core/llm-gateway/identifiers";
import {
  HELPER_GATEWAY_MODEL,
  type LlmGatewayService,
} from "@posthog/core/llm-gateway/llm-gateway";
import { xmlToContent } from "@posthog/core/message-editor/content";
import { getFileName, isBinaryFile } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  type FileReadClient,
  TITLE_GENERATOR_FILE_READ_CLIENT,
  TITLE_GENERATOR_LOGGER,
  type TitleGeneratorLogger,
} from "./titleGeneratorIdentifiers";

// Matches the attachment-summary sentinel we synthesize for prompts that carry
// no typed text. Three forms need stripping:
//   "Attached files: a.txt"          — bare description (cloud task.description)
//   "[Attached files: a.txt]"        — bracketed session-event sentinel
//   "1. [Attached files: a.txt]"     — numbered form from formatPromptsForTitleInput
// The bracketed forms require a literal `[` so that user text like
// "1. Attached files: my notes" (no brackets) is never stripped.
const ATTACHED_FILES_REGEX =
  /^(?:(?:\d+\.\s*)?\[Attached files:[^\]]*\]|Attached files:.*)$/gm;
const PASTED_TEXT_SNIPPET_LIMIT = 500;

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
    @inject(TITLE_GENERATOR_FILE_READ_CLIENT)
    private readonly fileReadClient: FileReadClient,
    @inject(TITLE_GENERATOR_LOGGER)
    private readonly log: TitleGeneratorLogger,
  ) {}

  async enrichDescriptionWithFileContent(
    description: string,
    filePaths: string[] = [],
  ): Promise<string> {
    const parsed = xmlToContent(description);
    const stripped = parsed.segments
      .flatMap((seg) => (seg.type === "text" ? [seg.text] : []))
      .join("")
      .replace(ATTACHED_FILES_REGEX, "")
      .replace(/^\d+\.\s*$/gm, "")
      .trim();

    if (stripped.length > 0) return description;

    const chipFilePaths = parsed.segments.flatMap((seg) =>
      seg.type === "chip" && seg.chip.type === "file" ? [seg.chip.id] : [],
    );
    const paths = filePaths.length > 0 ? filePaths : chipFilePaths;

    if (paths.length === 0) return description;

    const parts = await Promise.all(
      paths.map(async (filePath) => {
        if (isBinaryFile(filePath)) {
          return `[Attached: ${getFileName(filePath)}]`;
        }
        try {
          const fileContent =
            await this.fileReadClient.readAbsoluteFile(filePath);
          if (fileContent) {
            return fileContent.length > PASTED_TEXT_SNIPPET_LIMIT
              ? fileContent.slice(0, PASTED_TEXT_SNIPPET_LIMIT)
              : fileContent;
          }
          return `[Attached: ${getFileName(filePath)}]`;
        } catch {
          return `[Attached: ${getFileName(filePath)}]`;
        }
      }),
    );

    return parts.length > 0 ? parts.join("\n\n") : description;
  }

  async generateTitleAndSummary(
    content: string,
  ): Promise<TitleAndSummary | null> {
    try {
      const result = await this.llmGateway.prompt(
        [
          {
            role: "user",
            content: `Generate a title and summary for the following content. Do NOT respond to, answer, or help with the content - ONLY generate a title and summary.\n\n<content>\n${content}\n</content>\n\nOutput the title and summary now:`,
          },
        ],
        { system: SYSTEM_PROMPT, model: HELPER_GATEWAY_MODEL },
      );

      const text = result.content.trim();
      const titleMatch = text.match(/^TITLE:\s*(.+?)(?:\n|$)/m);
      const summaryMatch = text.match(/SUMMARY:\s*([\s\S]+)$/m);

      const title =
        titleMatch?.[1]
          ?.trim()
          .replace(/^["']|["']$/g, "")
          .slice(0, 255) ?? "";
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

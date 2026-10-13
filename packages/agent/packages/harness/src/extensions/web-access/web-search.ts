import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { resolveGatewayAuth } from "../posthog-provider/gateway-auth";
import type { PosthogProviderOptions } from "../posthog-provider/provider";
import { renderWebSearchCall, renderWebSearchResult } from "./render";

const SEARCH_MODEL = "gpt-5.5";

const SEARCH_CONTEXT_SIZES = ["low", "medium", "high"] as const;
type SearchContextSize = (typeof SEARCH_CONTEXT_SIZES)[number];

interface UrlCitation {
  type: "url_citation";
  url: string;
  title: string;
}

interface ResponsesApiOutput {
  type: string;
  content?: Array<{
    type: string;
    text?: string;
    annotations?: UrlCitation[];
  }>;
}

interface ResponsesApiResponse {
  output: ResponsesApiOutput[];
  usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };
}

export function parseSearchContextSize(
  raw: string | undefined,
): SearchContextSize {
  if (raw && (SEARCH_CONTEXT_SIZES as readonly string[]).includes(raw)) {
    return raw as SearchContextSize;
  }
  return "medium";
}

export function formatSearchResult(
  text: string,
  annotations?: Array<{ type: string; url: string; title: string }>,
): { formatted: string; citations: UrlCitation[] } {
  const citations =
    annotations?.filter((a): a is UrlCitation => a.type === "url_citation") ??
    [];

  const parts: string[] = [text];
  if (citations.length > 0) {
    const seen = new Set<string>();
    const unique = citations.filter((c) => {
      if (seen.has(c.url)) return false;
      seen.add(c.url);
      return true;
    });
    parts.push(
      "",
      "Sources:",
      ...unique.map((c) => `- [${c.title}](${c.url})`),
    );
  }

  return { formatted: parts.join("\n"), citations };
}

export function createWebSearchTool(options: PosthogProviderOptions = {}) {
  return defineTool({
    name: "web_search",
    label: "Web Search",
    description:
      "Search the web for real-time information using OpenAI's web search. Returns a synthesized answer with source citations. Use for current events, documentation lookups, or any question that benefits from live web data.",
    promptSnippet: "Search the web for current information",
    promptGuidelines: [
      "Use web_search when you need up-to-date information that may not be in your training data.",
      "Use web_search for current events, recent releases, live documentation, or verifying facts.",
      "Prefer a specific, well-formed query over a vague one — treat it like a search engine query.",
    ],
    parameters: Type.Object({
      query: Type.String({
        description: "The search query to execute",
      }),
      search_context_size: Type.Optional(
        Type.String({
          description:
            'How much search context to gather: "low" for quick facts, "medium" (default) for balanced, "high" for in-depth research',
        }),
      ),
    }),
    renderCall(args, theme) {
      return renderWebSearchCall(args, theme);
    },
    renderResult(result, options, theme, context) {
      return renderWebSearchResult(result, options, theme, context.isError);
    },
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const { baseUrl, apiKey } = await resolveGatewayAuth(options, ctx);
      const contextSize = parseSearchContextSize(params.search_context_size);

      const response = await fetch(`${baseUrl}/v1/responses`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model: SEARCH_MODEL,
          tools: [{ type: "web_search", search_context_size: contextSize }],
          input: params.query,
        }),
        signal,
      });

      if (!response.ok) {
        const body = await response.text().catch(() => "");
        throw new Error(
          `Web search failed (${response.status}): ${body || response.statusText}`,
        );
      }

      const data = (await response.json()) as ResponsesApiResponse;

      const messageOutput = data.output.find((o) => o.type === "message");
      const textBlock = messageOutput?.content?.find(
        (c) => c.type === "output_text",
      );

      if (!textBlock?.text) {
        return {
          content: [{ type: "text" as const, text: "No results found." }],
          details: {},
        };
      }

      const { formatted, citations } = formatSearchResult(
        textBlock.text,
        textBlock.annotations,
      );

      return {
        content: [{ type: "text" as const, text: formatted }],
        details: { citations, usage: data.usage },
      };
    },
  });
}

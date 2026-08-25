import { resolve } from "node:path";
import {
  type ExtensionAPI,
  type ExtensionFactory,
  isReadToolResult,
} from "@earendil-works/pi-coding-agent";
import { appendRichOutputPrompt } from "@posthog/shared/rich-output-prompt";
import {
  createEnrichment,
  enrichFileForAgent,
} from "../enrichment/file-enricher";

export interface PiEnrichmentConfig {
  apiUrl: string;
  publicApiUrl?: string;
  projectId: number;
  apiKey: string;
}

export function createPiEnrichmentExtension(config: PiEnrichmentConfig): {
  name: string;
  factory: ExtensionFactory;
} {
  return {
    name: "posthog-enricher",
    factory: (pi: ExtensionAPI) => {
      pi.on("before_agent_start", (event) => ({
        systemPrompt: appendRichOutputPrompt(event.systemPrompt),
      }));

      const enrichment = createEnrichment({
        apiUrl: config.apiUrl,
        publicApiUrl: config.publicApiUrl,
        projectId: config.projectId,
        getApiKey: () => config.apiKey,
      });
      if (!enrichment) {
        return;
      }

      pi.on("tool_result", async (event, ctx) => {
        if (!isReadToolResult(event) || event.isError) {
          return;
        }

        const rawPath = event.input.path;
        if (typeof rawPath !== "string") {
          return;
        }

        const textIndex = event.content.findIndex(
          (content) => content.type === "text",
        );
        const textContent = event.content[textIndex];
        if (!textContent || textContent.type !== "text") {
          return;
        }

        const filePath = resolve(ctx.cwd, rawPath.replace(/^@/, ""));
        const enriched = await enrichFileForAgent(
          enrichment.deps,
          filePath,
          textContent.text,
        );
        if (!enriched) {
          return;
        }

        const content = [...event.content];
        content[textIndex] = { type: "text", text: enriched };
        return { content };
      });

      pi.on("session_shutdown", () => {
        enrichment.dispose();
      });
    },
  };
}

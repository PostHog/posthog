import type {
  ExtensionFactory,
  InlineExtension,
} from "@earendil-works/pi-coding-agent";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { convertJsonSchemaToTypebox } from "@posthog/harness/extensions/mcp/schema";
import { z } from "zod";
import { enabledLocalTools, type LocalToolCtx } from "../adapters/local-tools";

const REPOSITORY_TOOL_NAMES = new Set(["list_repos", "clone_repo"]);
type NamedInlineExtension = Exclude<InlineExtension, ExtensionFactory>;

function toolLabel(name: string): string {
  return name
    .replaceAll("_", " ")
    .replace(/^./, (first) => first.toUpperCase());
}

function createRepositoryToolsFactory(cwd: string): ExtensionFactory {
  return (pi) => {
    const context: LocalToolCtx = { cwd };
    const tools = enabledLocalTools(context, { channelMode: true }).filter(
      (tool) => REPOSITORY_TOOL_NAMES.has(tool.name),
    );

    for (const localTool of tools) {
      const schema = z.object(localTool.schema);
      pi.registerTool(
        defineTool({
          name: localTool.name,
          label: toolLabel(localTool.name),
          description: localTool.description,
          promptSnippet: localTool.description,
          parameters: convertJsonSchemaToTypebox(z.toJSONSchema(schema)),
          execute: async (_toolCallId, params) => {
            const parsed = schema.safeParse(params);
            if (!parsed.success) {
              throw new Error(parsed.error.message);
            }
            const result = await localTool.handler(context, parsed.data);
            if (result.isError) {
              throw new Error(
                result.content.map((item) => item.text).join("\n"),
              );
            }
            return { content: result.content, details: {} };
          },
        }),
      );
    }
  };
}

export function createPiRepositoryToolsExtension(
  cwd: string,
): NamedInlineExtension {
  return {
    name: "posthog-code-repository-tools",
    factory: createRepositoryToolsFactory(cwd),
  };
}

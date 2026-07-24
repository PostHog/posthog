import fs from "node:fs";
import path from "node:path";
import type {
  ToolCall,
  ToolCallContent,
  ToolCallLocation,
  ToolCallUpdate,
  ToolKind,
} from "@agentclientprotocol/sdk";
import type {
  ToolResultBlockParam,
  ToolUseBlock,
  WebSearchToolResultBlockParam,
} from "@anthropic-ai/sdk/resources";
import type {
  BetaBashCodeExecutionToolResultBlockParam,
  BetaCodeExecutionToolResultBlockParam,
  BetaRequestMCPToolResultBlockParam,
  BetaTextEditorCodeExecutionToolResultBlockParam,
  BetaToolSearchToolResultBlockParam,
  BetaWebFetchToolResultBlockParam,
  BetaWebSearchToolResultBlockParam,
} from "@anthropic-ai/sdk/resources/beta.mjs";

const SYSTEM_REMINDER_REGEX =
  /\s*<system-reminder>[\s\S]*?<\/system-reminder>/g;

function stripSystemReminders(value: string): string {
  return value.replace(SYSTEM_REMINDER_REGEX, "");
}

import { resourceLink, text, toolContent } from "../../../utils/acp-content";
import type { EnrichedReadCache } from "../hooks";
import { getMcpToolMetadata } from "../mcp/tool-metadata";

type ToolInfo = Pick<ToolCall, "title" | "kind" | "content" | "locations">;

/**
 * Convert an absolute file path to a project-relative path for display.
 * Returns the original path if it's outside the project directory or if no cwd is provided.
 */
export function toDisplayPath(filePath: string, cwd?: string): string {
  if (!cwd) return filePath;
  const resolvedCwd = path.resolve(cwd);
  const resolvedFile = path.resolve(filePath);
  if (
    resolvedFile.startsWith(resolvedCwd + path.sep) ||
    resolvedFile === resolvedCwd
  ) {
    return path.relative(resolvedCwd, resolvedFile);
  }
  return filePath;
}

export function toolInfoFromToolUse(
  toolUse: Pick<ToolUseBlock, "name" | "input">,
  options?: {
    supportsTerminalOutput?: boolean;
    toolUseId?: string;
    cachedFileContent?: Record<string, string>;
    cwd?: string;
  },
): ToolInfo {
  const name = toolUse.name;
  const input = toolUse.input as Record<string, unknown> | undefined;

  switch (name) {
    case "Task":
    case "Agent":
      return {
        title: input?.description ? String(input.description) : name,
        kind: "think",
        content: input?.prompt
          ? toolContent().text(String(input.prompt)).build()
          : [],
      };

    case "NotebookRead":
      return {
        title: input?.notebook_path
          ? `Read Notebook ${String(input.notebook_path)}`
          : "Read Notebook",
        kind: "read",
        content: [],
        locations: input?.notebook_path
          ? [{ path: String(input.notebook_path) }]
          : [],
      };

    case "NotebookEdit":
      return {
        title: input?.notebook_path
          ? `Edit Notebook ${String(input.notebook_path)}`
          : "Edit Notebook",
        kind: "edit",
        content: input?.new_source
          ? toolContent().text(String(input.new_source)).build()
          : [],
        locations: input?.notebook_path
          ? [{ path: String(input.notebook_path) }]
          : [],
      };

    case "Bash":
      if (options?.supportsTerminalOutput && options?.toolUseId) {
        return {
          title: input?.description
            ? String(input.description)
            : "Execute command",
          kind: "execute",
          content: [{ type: "terminal", terminalId: options.toolUseId }],
        };
      }
      return {
        title: input?.description
          ? String(input.description)
          : "Execute command",
        kind: "execute",
        content: input?.command
          ? toolContent().text(String(input.command)).build()
          : [],
      };

    case "BashOutput":
      return {
        title: "Tail Logs",
        kind: "execute",
        content: [],
      };

    case "KillShell":
      return {
        title: "Kill Process",
        kind: "execute",
        content: [],
      };

    case "Read": {
      let limit = "";
      const inputLimit = input?.limit as number | undefined;
      const inputOffset = (input?.offset as number | undefined) ?? 1;
      if (inputLimit) {
        limit = ` (${inputOffset} - ${inputOffset + inputLimit - 1})`;
      } else if (inputOffset > 1) {
        limit = ` (from line ${inputOffset})`;
      }
      const displayPath = input?.file_path
        ? toDisplayPath(String(input.file_path), options?.cwd)
        : "File";
      return {
        title: `Read ${displayPath}${limit}`,
        kind: "read",
        locations: input?.file_path
          ? [
              {
                path: String(input.file_path),
                line: inputOffset,
              },
            ]
          : [],
        content: [],
      };
    }

    case "LS":
      return {
        title: `List the ${input?.path ? `\`${String(input.path)}\`` : "current"} directory's contents`,
        kind: "search",
        content: [],
        locations: [],
      };

    case "Edit": {
      const filePath = input?.file_path ? String(input.file_path) : undefined;
      const displayPath = filePath
        ? toDisplayPath(filePath, options?.cwd)
        : undefined;
      let oldText: string | null = input?.old_string
        ? String(input.old_string)
        : null;
      let newText: string = input?.new_string ? String(input.new_string) : "";

      // try to display a rich diff by first checking if file content is cached
      // and valid (old_text exists in the content), then fall back to reading
      // file from disk, then fall back to fragemented snippet diff
      if (filePath && oldText !== null) {
        const fileContent = resolveFileContent(
          filePath,
          oldText,
          options?.cachedFileContent,
        );
        if (fileContent) {
          const newContent = input?.replace_all
            ? fileContent.replaceAll(oldText, newText)
            : fileContent.replace(oldText, newText);
          oldText = fileContent;
          newText = newContent;
        }
      }

      return {
        title: displayPath ? `Edit \`${displayPath}\`` : "Edit",
        kind: "edit",
        content:
          input && filePath
            ? [
                {
                  type: "diff",
                  path: filePath,
                  oldText,
                  newText,
                },
              ]
            : [],
        locations: filePath ? [{ path: filePath }] : [],
      };
    }

    case "Write": {
      let contentResult: ToolCallContent[] = [];
      const writeFilePath = input?.file_path
        ? String(input.file_path)
        : undefined;
      const writeDisplayPath = writeFilePath
        ? toDisplayPath(writeFilePath, options?.cwd)
        : undefined;
      const contentStr = input?.content ? String(input.content) : undefined;
      if (writeFilePath) {
        let oldContent: string | null = null;
        if (
          options?.cachedFileContent &&
          writeFilePath in options.cachedFileContent
        ) {
          oldContent = options.cachedFileContent[writeFilePath];
        } else {
          try {
            oldContent = fs.readFileSync(writeFilePath, "utf-8");
          } catch {
            // File doesn't exist — genuinely a new file
          }
        }
        contentResult = toolContent()
          .diff(writeFilePath, oldContent, contentStr ?? "")
          .build();
      } else if (contentStr) {
        contentResult = toolContent().text(contentStr).build();
      }
      return {
        title: writeDisplayPath ? `Write ${writeDisplayPath}` : "Write",
        kind: "edit",
        content: contentResult,
        locations: writeFilePath ? [{ path: writeFilePath }] : [],
      };
    }

    case "Glob": {
      let label = "Find";
      const pathStr = input?.path ? String(input.path) : undefined;
      if (pathStr) {
        label += ` "${pathStr}"`;
      }
      if (input?.pattern) {
        label += ` "${String(input.pattern)}"`;
      }
      return {
        title: label,
        kind: "search",
        content: [],
        locations: pathStr ? [{ path: pathStr }] : [],
      };
    }

    case "Grep": {
      let label = "grep";

      if (input?.["-i"]) {
        label += " -i";
      }
      if (input?.["-n"]) {
        label += " -n";
      }

      if (input?.["-A"] !== undefined) {
        label += ` -A ${input["-A"]}`;
      }
      if (input?.["-B"] !== undefined) {
        label += ` -B ${input["-B"]}`;
      }
      if (input?.["-C"] !== undefined) {
        label += ` -C ${input["-C"]}`;
      }

      if (input?.output_mode) {
        switch (input.output_mode) {
          case "files_with_matches":
            label += " -l";
            break;
          case "count":
            label += " -c";
            break;
          default:
            break;
        }
      }

      if (input?.head_limit !== undefined) {
        label += ` | head -${input.head_limit}`;
      }

      if (input?.glob) {
        label += ` --include="${String(input.glob)}"`;
      }

      if (input?.type) {
        label += ` --type=${String(input.type)}`;
      }

      if (input?.multiline) {
        label += " -P";
      }

      if (input?.pattern) {
        label += ` "${String(input.pattern)}"`;
      }

      if (input?.path) {
        label += ` ${String(input.path)}`;
      }

      return {
        title: label,
        kind: "search",
        content: [],
      };
    }

    case "WebFetch":
      return {
        title: "Fetch",
        kind: "fetch",
        content: input?.url
          ? [
              {
                type: "content",
                content: resourceLink(String(input.url), String(input.url), {
                  description: input?.prompt ? String(input.prompt) : undefined,
                }),
              },
            ]
          : [],
      };

    case "WebSearch": {
      let label = `"${input?.query ? String(input.query) : ""}"`;
      const allowedDomains = input?.allowed_domains as string[] | undefined;
      const blockedDomains = input?.blocked_domains as string[] | undefined;

      if (allowedDomains && allowedDomains.length > 0) {
        label += ` (allowed: ${allowedDomains.join(", ")})`;
      }

      if (blockedDomains && blockedDomains.length > 0) {
        label += ` (blocked: ${blockedDomains.join(", ")})`;
      }

      return {
        title: label,
        kind: "fetch",
        content: [],
      };
    }

    case "TaskCreate": {
      const subject =
        typeof input?.subject === "string" ? input.subject : undefined;
      return {
        title: subject ? `Create task: ${subject}` : "Create task",
        kind: "think",
        content: [],
      };
    }

    case "TaskUpdate": {
      const subject =
        typeof input?.subject === "string" ? input.subject : undefined;
      return {
        title: subject ? `Update task: ${subject}` : "Update task",
        kind: "think",
        content: [],
      };
    }

    case "TaskList":
      return {
        title: "List tasks",
        kind: "think",
        content: [],
      };

    case "TaskGet":
      return {
        title: "Get task",
        kind: "think",
        content: [],
      };

    case "Skill": {
      const skill = typeof input?.skill === "string" ? input.skill : undefined;
      const skillArgs =
        typeof input?.args === "string" ? input.args : undefined;
      return {
        title: skill ? `Skill: ${skill}` : "Skill",
        kind: "other",
        content: skillArgs ? toolContent().text(skillArgs).build() : [],
      };
    }

    case "ExitPlanMode":
      return {
        title: "Ready to code?",
        kind: "switch_mode",
        content: input?.plan
          ? toolContent().text(String(input.plan)).build()
          : [],
      };

    case "AskUserQuestion": {
      const questions = input?.questions as
        | Array<{ question?: string }>
        | undefined;
      return {
        title: questions?.[0]?.question || "Question",
        kind: "other" as ToolKind,
        content: questions
          ? toolContent()
              .text(JSON.stringify(questions, null, 2))
              .build()
          : [],
      };
    }

    case "Other": {
      let output: string;
      try {
        output = JSON.stringify(input, null, 2);
      } catch {
        output = typeof input === "string" ? input : "{}";
      }
      return {
        title: name || "Unknown Tool",
        kind: "other",
        content: toolContent().text(`\`\`\`json\n${output}\`\`\``).build(),
      };
    }

    default: {
      if (name?.startsWith("mcp__")) {
        return mcpToolInfo(name, input);
      }
      return {
        title: name || "Unknown Tool",
        kind: "other",
        content: [],
      };
    }
  }
}

function mcpToolInfo(
  name: string,
  _input: Record<string, unknown> | undefined,
): ToolInfo {
  const metadata = getMcpToolMetadata(name);
  // Fallback: parse tool name from mcp__<server>__<tool> prefix
  const title =
    metadata?.name ?? (name.split("__").slice(2).join("__") || name);

  return {
    title,
    kind: "other",
    content: [],
  };
}

interface StructuredPatchHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: string[];
}

interface StructuredPatch {
  oldFileName: string;
  newFileName: string;
  hunks: StructuredPatchHunk[];
}

export function toolUpdateFromEditToolResponse(
  toolResponse: unknown,
): { content: ToolCallContent[]; locations: ToolCallLocation[] } | null {
  if (!toolResponse || typeof toolResponse !== "object") return null;
  const response = toolResponse as Record<string, unknown>;

  const patches = response.structuredPatch as StructuredPatch[] | undefined;
  if (!Array.isArray(patches) || patches.length === 0) return null;

  const content: ToolCallContent[] = [];
  const locations: ToolCallLocation[] = [];

  for (const patch of patches) {
    if (!patch.hunks || patch.hunks.length === 0) continue;

    const filePath = patch.newFileName || patch.oldFileName;

    const oldLines: string[] = [];
    const newLines: string[] = [];
    for (const hunk of patch.hunks) {
      for (const line of hunk.lines) {
        if (line.startsWith("-")) {
          oldLines.push(line.slice(1));
        } else if (line.startsWith("+")) {
          newLines.push(line.slice(1));
        } else if (line.startsWith(" ")) {
          oldLines.push(line.slice(1));
          newLines.push(line.slice(1));
        }
      }
    }

    content.push({
      type: "diff",
      path: filePath,
      oldText: oldLines.join("\n"),
      newText: newLines.join("\n"),
    });

    const firstHunk = patch.hunks[0];
    locations.push({
      path: filePath,
      line: firstHunk.newStart,
    });
  }

  if (content.length === 0) return null;
  return { content, locations };
}

export function toolUpdateFromToolResult(
  toolResult:
    | ToolResultBlockParam
    | BetaWebSearchToolResultBlockParam
    | BetaWebFetchToolResultBlockParam
    | WebSearchToolResultBlockParam
    | BetaCodeExecutionToolResultBlockParam
    | BetaBashCodeExecutionToolResultBlockParam
    | BetaTextEditorCodeExecutionToolResultBlockParam
    | BetaRequestMCPToolResultBlockParam
    | BetaToolSearchToolResultBlockParam,
  toolUse: Pick<ToolUseBlock, "name" | "input"> | undefined,
  options?: {
    supportsTerminalOutput?: boolean;
    toolUseId?: string;
    cachedFileContent?: Record<string, string>;
    enrichedReadCache?: EnrichedReadCache;
  },
): Pick<ToolCallUpdate, "title" | "content" | "locations" | "_meta"> {
  if (
    "is_error" in toolResult &&
    toolResult.is_error &&
    toolResult.content &&
    (toolResult.content as unknown[]).length > 0 &&
    // Bash errors keep rendering through the terminal-output channel below.
    !(toolUse?.name === "Bash" && options?.supportsTerminalOutput)
  ) {
    return toAcpContentUpdate(toolResult.content, true);
  }

  switch (toolUse?.name) {
    case "Read": {
      const cache = options?.enrichedReadCache;
      const enriched =
        cache && options?.toolUseId ? cache.get(options.toolUseId) : undefined;
      if (enriched !== undefined && cache && options?.toolUseId) {
        cache.delete(options.toolUseId);
        return {
          content: [
            {
              type: "content" as const,
              content: text(markdownEscape(enriched)),
            },
          ],
        };
      }
      if (Array.isArray(toolResult.content) && toolResult.content.length > 0) {
        return {
          content: toolResult.content.map((item) => {
            const itemObj = item as {
              type?: string;
              text?: string;
              source?: { data?: string; media_type?: string };
            };
            if (itemObj.type === "text") {
              return {
                type: "content" as const,
                content: text(
                  markdownEscape(stripSystemReminders(itemObj.text ?? "")),
                ),
              };
            }
            if (itemObj.type === "image" && itemObj.source) {
              return {
                type: "content" as const,
                content: {
                  type: "image" as const,
                  data: itemObj.source.data ?? "",
                  mimeType: itemObj.source.media_type ?? "image/png",
                },
              };
            }
            return {
              type: "content" as const,
              content: item as { type: "text"; text: string },
            };
          }),
        };
      } else if (
        typeof toolResult.content === "string" &&
        toolResult.content.length > 0
      ) {
        return {
          content: toolContent()
            .text(markdownEscape(stripSystemReminders(toolResult.content)))
            .build(),
        };
      }
      return {};
    }

    case "Bash": {
      const result = toolResult.content;
      const terminalId =
        "tool_use_id" in toolResult ? String(toolResult.tool_use_id) : "";
      const isError = "is_error" in toolResult && toolResult.is_error;

      let output = "";
      let exitCode = isError ? 1 : 0;

      if (
        result &&
        typeof result === "object" &&
        "type" in result &&
        (result as { type: string }).type === "bash_code_execution_result"
      ) {
        const bashResult = result as {
          stdout?: string;
          stderr?: string;
          return_code: number;
        };
        output = [bashResult.stdout, bashResult.stderr]
          .filter(Boolean)
          .join("\n");
        exitCode = bashResult.return_code;
      } else if (typeof result === "string") {
        output = result;
      } else if (Array.isArray(result) && result.length > 0) {
        const textOnly = result.every(
          (c) =>
            c &&
            typeof c === "object" &&
            typeof (c as { text?: unknown }).text === "string",
        );
        if (textOnly) {
          output = result
            .map((c: { text?: string }) => c.text ?? "")
            .join("\n");
        } else {
          // Binary payloads can't ride the terminal-output _meta channel;
          // surface image/mixed content as ACP content blocks instead.
          return toAcpContentUpdate(result, isError === true);
        }
      }

      if (options?.supportsTerminalOutput) {
        return {
          content: [{ type: "terminal" as const, terminalId }],
          _meta: {
            terminal_info: {
              terminal_id: terminalId,
            },
            terminal_output: {
              terminal_id: terminalId,
              data: output,
            },
            terminal_exit: {
              terminal_id: terminalId,
              exit_code: exitCode,
              signal: null,
            },
          },
        };
      }
      if (output.trim()) {
        return {
          content: toolContent()
            .text(`\`\`\`console\n${output.trimEnd()}\n\`\`\``)
            .build(),
        };
      }
      return {};
    }
    case "Edit":
    case "Write":
      return {};

    case "ExitPlanMode": {
      return { title: "Exited Plan Mode" };
    }
    case "AskUserQuestion": {
      const content = toolResult.content;
      if (Array.isArray(content) && content.length > 0) {
        const firstItem = content[0];
        if (
          typeof firstItem === "object" &&
          firstItem !== null &&
          "text" in firstItem
        ) {
          return {
            title: "Answer received",
            content: toolContent().text(String(firstItem.text)).build(),
          };
        }
      }
      return { title: "Question answered" };
    }
    case "WebFetch": {
      const input = toolUse?.input as Record<string, unknown> | undefined;
      const url = input?.url ? String(input.url) : "";
      const prompt = input?.prompt ? String(input.prompt) : undefined;

      const resultContent = toAcpContentUpdate(
        toolResult.content,
        "is_error" in toolResult ? toolResult.is_error : false,
      );

      const content: ToolCallContent[] = [];
      if (url) {
        content.push({
          type: "content",
          content: resourceLink(url, url, {
            description: prompt,
          }),
        });
      }
      if (resultContent.content) {
        content.push(...resultContent.content);
      }

      return { content };
    }
    default: {
      return toAcpContentUpdate(
        toolResult.content,
        "is_error" in toolResult ? toolResult.is_error : false,
      );
    }
  }
}

function itemToText(item: unknown): string | null {
  if (!item || typeof item !== "object") return null;
  const obj = item as Record<string, unknown>;
  // Standard text block
  if (obj.type === "text" && typeof obj.text === "string") {
    return stripSystemReminders(obj.text);
  }
  // Any other structured object — serialize it
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return null;
  }
}

function toAcpContentUpdate(
  content: unknown,
  isError: boolean = false,
): Pick<ToolCallUpdate, "content"> {
  if (Array.isArray(content) && content.length > 0) {
    const texts: string[] = [];
    for (const item of content) {
      const t = itemToText(item);
      if (t) texts.push(t);
    }
    if (texts.length > 0) {
      const combined = texts.join("\n");
      return {
        content: toolContent()
          .text(isError ? `\`\`\`\n${combined}\n\`\`\`` : combined)
          .build(),
      };
    }
  } else if (typeof content === "string" && content.length > 0) {
    return {
      content: toolContent()
        .text(isError ? `\`\`\`\n${content}\n\`\`\`` : content)
        .build(),
    };
  } else if (content && typeof content === "object") {
    try {
      const json = JSON.stringify(content, null, 2);
      if (json && json !== "{}") {
        return {
          content: toolContent().text(json).build(),
        };
      }
    } catch {
      // ignore serialization errors
    }
  }
  return {};
}

/**
 * attempt to resolve full file contents for diff generation
 *
 * 1) check file content cache exists, and is valid (old_text in content)
 * 2) if missing or invalid, read file from disk
 * 3) if both fail, return null, we'll fall back to fragmented snippet diff
 */
function resolveFileContent(
  filePath: string,
  oldText: string,
  cachedFileContent?: Record<string, string>,
): string | null {
  if (cachedFileContent && filePath in cachedFileContent) {
    const cached = cachedFileContent[filePath];
    if (cached.includes(oldText)) {
      return cached;
    }
  }

  try {
    const content = fs.readFileSync(filePath, "utf-8");
    if (content.includes(oldText)) {
      return content;
    }
  } catch {
    return null;
  }

  return null;
}

function markdownEscape(text: string): string {
  let escapedText = "```";
  for (const [m] of text.matchAll(/^```+/gm)) {
    while (m.length >= escapedText.length) {
      escapedText += "`";
    }
  }
  return `${escapedText}\n${text}${text.endsWith("\n") ? "" : "\n"}${escapedText}`;
}

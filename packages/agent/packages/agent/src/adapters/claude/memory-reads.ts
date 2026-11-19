import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { HookCallback, HookInput } from "@anthropic-ai/claude-agent-sdk";

export interface MemoryFile {
  slug: string;
  file: string;
}

export interface MemoryRead extends MemoryFile {
  tool: string;
  toolCallId: string;
  agentId?: string;
}

export type OnMemoryRead = (read: MemoryRead) => void;

const INDEX_FILE = "MEMORY.md";
const NON_READ_TOOLS = new Set([
  "Write",
  "Edit",
  "MultiEdit",
  "NotebookEdit",
  "Agent",
  "Task",
]);
const MEMORY_FILE_PATH = /\/projects\/([^/]+)\/memory\/([^/]+\.md)$/;

function claudeProjectsDir(): string {
  return path.join(
    process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"),
    "projects",
  );
}

export function memoryFileFromPath(filePath: string): MemoryFile | null {
  const match = MEMORY_FILE_PATH.exec(filePath);
  if (!match || match[2] === INDEX_FILE) return null;
  return { slug: match[1], file: match[2] };
}

async function listMemoryFiles(projectsDir: string): Promise<MemoryFile[]> {
  const slugs = await fs.readdir(projectsDir).catch(() => []);
  const perSlug = await Promise.all(
    slugs.map(async (slug) => {
      const files = await fs
        .readdir(path.join(projectsDir, slug, "memory"))
        .catch(() => []);
      return files
        .filter((file) => file.endsWith(".md") && file !== INDEX_FILE)
        .map((file) => ({ slug, file }));
    }),
  );
  return perSlug.flat();
}

function namesFile(text: string, file: string): boolean {
  const escaped = file.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![\\w.-])${escaped}(?![\\w-])`).test(text);
}

export async function findMemoryFilesNamed(
  text: string,
  projectsDir: string,
): Promise<MemoryFile[]> {
  if (!text.includes(".md")) return [];
  const named = (await listMemoryFiles(projectsDir)).filter(({ file }) =>
    namesFile(text, file),
  );
  const inPath = ({ slug, file }: MemoryFile) =>
    text.includes(`${slug}/memory/${file}`);
  const filesWithPath = new Set(named.filter(inPath).map(({ file }) => file));
  return named.filter(
    (candidate) => !filesWithPath.has(candidate.file) || inPath(candidate),
  );
}

export const createMemoryReadHook =
  (
    onMemoryRead: OnMemoryRead,
    projectsDir: string = claudeProjectsDir(),
  ): HookCallback =>
  async (input: HookInput) => {
    if (
      input.hook_event_name !== "PostToolUse" ||
      NON_READ_TOOLS.has(input.tool_name)
    ) {
      return { continue: true };
    }
    let text = JSON.stringify(input.tool_input) ?? "";
    if (input.tool_name === "Grep" && text.includes("/memory")) {
      text += JSON.stringify(input.tool_response) ?? "";
    }
    for (const memoryFile of await findMemoryFilesNamed(text, projectsDir)) {
      onMemoryRead({
        ...memoryFile,
        tool: input.tool_name,
        toolCallId: input.tool_use_id,
        agentId: input.agent_id,
      });
    }
    return { continue: true };
  };

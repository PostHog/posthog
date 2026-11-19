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
  return new RegExp(
    `(?:(?<![\\w./-])|(?<=(?<![\\w.-])memory/))${escaped}(?![\\w-])`,
  ).test(text);
}

function projectSlug(cwd: string): string {
  return cwd.replace(/[^a-zA-Z0-9]/g, "-");
}

export async function findMemoryFilesNamed(
  text: string,
  projectsDir: string,
  cwd: string,
): Promise<MemoryFile[]> {
  if (!text.includes(".md")) return [];
  const named = (await listMemoryFiles(projectsDir)).filter(({ file }) =>
    namesFile(text, file),
  );
  const inPath = ({ slug, file }: MemoryFile) =>
    text.includes(`${slug}/memory/${file}`);
  const cwdSlug = projectSlug(cwd);
  return named.filter((candidate) => {
    const sameName = named.filter(({ file }) => file === candidate.file);
    if (sameName.some(inPath)) return inPath(candidate);
    if (sameName.length === 1) return true;
    return candidate.slug === cwdSlug;
  });
}

function grepResultPaths(response: unknown): string[] {
  if (!response || typeof response !== "object") return [];
  const { filenames, content } = response as {
    filenames?: unknown;
    content?: unknown;
  };
  const paths = Array.isArray(filenames)
    ? filenames.filter((name): name is string => typeof name === "string")
    : [];
  if (typeof content === "string") {
    for (const line of content.split("\n")) {
      const match = /^([^:]+\.md)[:-]/.exec(line);
      if (match) paths.push(match[1]);
    }
  }
  return paths;
}

function accessedPaths(input: HookInput): string {
  if (input.hook_event_name !== "PostToolUse") return "";
  const toolInput = (input.tool_input ?? {}) as Record<string, unknown>;
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  switch (input.tool_name) {
    case "Read":
      return text(toolInput.file_path);
    case "Bash":
      return text(toolInput.command).replace(/>>?\s*\S+/g, " ");
    case "Grep": {
      const target = text(toolInput.path);
      return target.includes("/memory")
        ? [target, ...grepResultPaths(input.tool_response)].join("\n")
        : target;
    }
    default:
      return "";
  }
}

export const createMemoryReadHook =
  (
    onMemoryRead: OnMemoryRead,
    projectsDir: string = claudeProjectsDir(),
  ): HookCallback =>
  async (input: HookInput) => {
    if (input.hook_event_name !== "PostToolUse") return { continue: true };
    const memoryFiles = await findMemoryFilesNamed(
      accessedPaths(input),
      projectsDir,
      input.cwd,
    );
    for (const memoryFile of memoryFiles) {
      onMemoryRead({
        ...memoryFile,
        tool: input.tool_name,
        toolCallId: input.tool_use_id,
        agentId: input.agent_id,
      });
    }
    return { continue: true };
  };

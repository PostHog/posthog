import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { TaskRunState } from "@posthog/agent-contracts";

// The sandbox image may ship these files, so only the text between the markers is ever replaced.
const BLOCK_START = "<!-- posthog -->";
const BLOCK_END = "<!-- /posthog -->";
const BLOCK_RE = new RegExp(
  `\\n*${escapeRegExp(BLOCK_START)}[\\s\\S]*?${escapeRegExp(BLOCK_END)}\\n*`,
  "g",
);

export interface AgentInstructionFilesOptions {
  home?: string;
  claudeConfigDir?: string;
  codexHome?: string;
}

// Pi's dir is fixed at ~/.pi/agent because the Pi host environment allowlist drops the variable that moves it.
export function getAgentInstructionFilePaths(
  options: AgentInstructionFilesOptions = {},
): string[] {
  const home = options.home ?? homedir();
  // `||`, not `??`: the adapters treat an empty variable as unset, and so must this.
  const claudeConfigDir =
    options.claudeConfigDir ??
    (process.env.CLAUDE_CONFIG_DIR || join(home, ".claude"));
  const codexHome =
    options.codexHome ?? (process.env.CODEX_HOME || join(home, ".codex"));
  return [
    join(claudeConfigDir, "CLAUDE.md"),
    join(codexHome, "AGENTS.md"),
    join(home, ".pi", "agent", "AGENTS.md"),
  ];
}

// Returns null when nothing is left, which means the file must be deleted.
export function applyInstructionsBlock(
  existing: string | null,
  instructions: string | null,
): string | null {
  const rest = (existing ?? "").replace(BLOCK_RE, "\n\n").trim();
  if (!instructions) {
    return rest ? `${rest}\n` : null;
  }
  // A marker inside the text would end the block early, and a later clear would leave the rest behind.
  const body = instructions
    .split(BLOCK_START)
    .join("")
    .split(BLOCK_END)
    .join("")
    .trim();
  const block = `${BLOCK_START}\n${body}\n${BLOCK_END}`;
  return rest ? `${rest}\n\n${block}\n` : `${block}\n`;
}

export interface AgentInstructionFilesLogger {
  info(message: string, data?: unknown): void;
  warn(message: string, data?: unknown): void;
}

export interface AgentInstructionFilesSyncContext {
  taskId: string;
  runId: string;
}

export class AgentInstructionFiles {
  constructor(
    private readonly logger: AgentInstructionFilesLogger,
    private readonly paths: string[] = getAgentInstructionFilePaths(),
  ) {}

  // A null run state means the fetch failed, so the files keep what an earlier session wrote.
  // A run state without the key clears the block, so a snapshot never carries removed text.
  async sync(
    runState: TaskRunState | null | undefined,
    context: AgentInstructionFilesSyncContext,
  ): Promise<string | null> {
    if (runState === null || runState === undefined) {
      return null;
    }
    const instructions = runState.agent_instructions?.trim() || null;
    const errors: { path: string; message: string }[] = [];
    for (const path of this.paths) {
      try {
        await this.writeOne(path, instructions);
      } catch (error) {
        errors.push({
          path,
          message: error instanceof Error ? error.message : String(error),
        });
      }
    }
    if (errors.length > 0) {
      this.logger.warn("Failed to write agent instruction files", {
        ...context,
        errors,
      });
    } else if (instructions) {
      this.logger.info("Wrote agent instruction files", {
        ...context,
        length: instructions.length,
      });
    }
    return instructions;
  }

  private async writeOne(
    path: string,
    instructions: string | null,
  ): Promise<void> {
    const existing = await readFile(path, "utf-8").catch(
      (error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") {
          return null;
        }
        throw error;
      },
    );
    const next = applyInstructionsBlock(existing, instructions);
    if (next === existing) {
      return;
    }
    if (next === null) {
      await rm(path, { force: true });
      return;
    }
    await mkdir(dirname(path), { recursive: true });
    // A harness reading the file mid-write must see the old or the new content, never half of it.
    const tmpPath = `${path}.${process.pid}.tmp`;
    await writeFile(tmpPath, next, "utf-8");
    await rename(tmpPath, path);
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

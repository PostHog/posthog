import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { StoredLogEntry, Task } from "@posthog/shared";

const LOCAL_SESSIONS = join(homedir(), ".config", "posthog-tui", "local");
const SESSION_SUFFIX = ".jsonl";
// Chats started before local chats had a task row; their pi session files still carry this id.
export const LEGACY_PREFIX = "local:";
const HARNESS_SUFFIX = ".harness";
const ACP_SUFFIX = ".acp";

// A Claude Code chat's log on this machine: its ACP messages, and Claude's session id so a reopen resumes it.
export class AcpLog {
  constructor(private readonly path: string) {}

  load(): { sessionId?: string; entries: StoredLogEntry[] } {
    let sessionId: string | undefined;
    const entries: StoredLogEntry[] = [];
    let text = "";
    try {
      text = readFileSync(this.path, "utf8");
    } catch {
      return { entries };
    }
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const parsed = JSON.parse(line) as StoredLogEntry & {
          sessionId?: string;
        };
        if (parsed.type === "session") sessionId = parsed.sessionId;
        else entries.push(parsed);
      } catch {}
    }
    return { ...(sessionId && { sessionId }), entries };
  }

  append(entry: StoredLogEntry): void {
    appendFileSync(this.path, `${JSON.stringify(entry)}\n`);
  }

  session(sessionId: string): void {
    appendFileSync(
      this.path,
      `${JSON.stringify({ type: "session", sessionId })}\n`,
    );
  }
}

export type LocalHarness = "pi" | "claude";

export interface UnlinkedChat {
  legacyId: string;
  // The chat's first message, which names its task.
  firstMessage: string;
  // The folder pi ran in, from the session header.
  cwd: string | null;
}

interface SessionLine {
  type?: string;
  cwd?: string;
  message?: { role?: string; content?: unknown };
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .flatMap((part: { type?: string; text?: unknown }) =>
      part?.type === "text" && typeof part.text === "string" ? [part.text] : [],
    )
    .join("\n");
}

// The pi session files of this machine's local chats, one per task, named by the task id.
export class LocalChats {
  constructor(private readonly dir: string = LOCAL_SESSIONS) {}

  sessionFile(id: string): string {
    mkdirSync(this.dir, { recursive: true });
    return join(this.dir, `${id}${SESSION_SUFFIX}`);
  }

  private markerFile(id: string): string {
    return join(this.dir, `${id}${HARNESS_SUFFIX}`);
  }

  private acpFile(id: string): string {
    return join(this.dir, `${id}${ACP_SUFFIX}`);
  }

  acpLog(id: string): AcpLog {
    mkdirSync(this.dir, { recursive: true });
    return new AcpLog(this.acpFile(id));
  }

  // Which agent the chat runs, written when it first starts so a later /billing never changes it.
  remember(id: string, harness: LocalHarness): void {
    mkdirSync(this.dir, { recursive: true });
    writeFileSync(this.markerFile(id), harness);
  }

  harnessOf(id: string): LocalHarness | null {
    try {
      const marker = readFileSync(this.markerFile(id), "utf8").trim();
      if (marker === "claude" || marker === "pi") return marker;
    } catch {}
    return existsSync(this.sessionFile(id)) ? "pi" : null;
  }

  // Task ids of the local chats with a session file, with when each last changed.
  list(): Map<string, number> {
    const chats = new Map<string, number>();
    for (const name of [
      ...this.names(),
      ...this.names(HARNESS_SUFFIX),
      ...this.names(ACP_SUFFIX),
    ]) {
      const id = name.slice(0, name.lastIndexOf("."));
      if (id.startsWith(LEGACY_PREFIX)) continue;
      const changed = statSync(join(this.dir, name)).mtimeMs;
      chats.set(id, Math.max(chats.get(id) ?? 0, changed));
    }
    return chats;
  }

  // Chats that have no task row yet.
  unlinked(): UnlinkedChat[] {
    return this.names()
      .filter((name) => name.startsWith(LEGACY_PREFIX))
      .map((name) => {
        const lines = readFileSync(join(this.dir, name), "utf8")
          .split("\n")
          .flatMap((line): SessionLine[] => {
            try {
              return line.trim() ? [JSON.parse(line) as SessionLine] : [];
            } catch {
              return [];
            }
          });
        const header = lines.find((line) => line.type === "session");
        const first = lines.find(
          (line) => line.type === "message" && line.message?.role === "user",
        );
        return {
          legacyId: name.slice(0, -SESSION_SUFFIX.length),
          firstMessage: textOf(first?.message?.content).trim(),
          cwd: header?.cwd ?? null,
        };
      });
  }

  // Renames the session file, so the chat resumes under its task and is never linked twice.
  link(legacyId: string, taskId: string): void {
    for (const file of [this.sessionFile, this.markerFile, this.acpFile]) {
      try {
        renameSync(file.call(this, legacyId), file.call(this, taskId));
      } catch (error) {
        // A Claude chat has no session file, and a pi chat may have no marker yet.
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
  }

  // Moves the chat's session file into cleared/, so its agent starts on an empty conversation under the same task.
  // The old conversation stays on disk in case the user wants it back.
  archive(id: string): void {
    const cleared = join(this.dir, "cleared");
    mkdirSync(cleared, { recursive: true });
    for (const [file, suffix] of [
      [this.sessionFile(id), SESSION_SUFFIX],
      [this.acpFile(id), ACP_SUFFIX],
    ]) {
      try {
        renameSync(file, join(cleared, `${id}.${Date.now()}${suffix}`));
      } catch (error) {
        // A chat whose agent has not answered yet has no file, so there is nothing to move.
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
  }

  private names(suffix: string = SESSION_SUFFIX): string[] {
    try {
      return readdirSync(this.dir).filter((name) => name.endsWith(suffix));
    } catch {
      return [];
    }
  }
}

// Gives each chat without a task row one, then its session file the task's id.
// A chat whose task could not be made stays as it is, and the next start tries again.
export async function linkLocalChats(
  chats: LocalChats,
  createTask: (chat: UnlinkedChat) => Promise<Task>,
): Promise<Map<string, Task>> {
  const linked = new Map<string, Task>();
  for (const chat of chats.unlinked()) {
    try {
      const task = await createTask(chat);
      chats.link(chat.legacyId, task.id);
      linked.set(chat.legacyId, task);
    } catch {
      // Left for the next start.
    }
  }
  return linked;
}

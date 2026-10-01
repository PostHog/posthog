import {
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  statSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { Task } from "@posthog/shared";

const LOCAL_SESSIONS = join(homedir(), ".config", "posthog-tui", "local");
const SESSION_SUFFIX = ".jsonl";
// Chats started before local chats had a task row; their pi session files still carry this id.
export const LEGACY_PREFIX = "local:";

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

  // Task ids of the local chats with a session file, with when each last changed.
  list(): Map<string, number> {
    const chats = new Map<string, number>();
    for (const name of this.names()) {
      const id = name.slice(0, -SESSION_SUFFIX.length);
      if (id.startsWith(LEGACY_PREFIX)) continue;
      chats.set(id, statSync(join(this.dir, name)).mtimeMs);
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
    renameSync(this.sessionFile(legacyId), this.sessionFile(taskId));
  }

  private names(): string[] {
    try {
      return readdirSync(this.dir).filter((name) =>
        name.endsWith(SESSION_SUFFIX),
      );
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

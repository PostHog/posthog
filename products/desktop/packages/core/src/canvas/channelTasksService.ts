import { inject, injectable } from "inversify";
import type { ChannelTaskRecord } from "./channelTaskSchemas";
import {
  DESKTOP_FS_CLIENT,
  type DesktopFsClient,
  type FsEntryBase,
} from "./desktopFsClient";

const TASK_TYPE = "task";
const HOME_FOLDER = "Unfiled/Tasks";

type FsEntry = FsEntryBase;

/**
 * Tracks which tasks are filed to a channel by writing a `task` row to the
 * project's desktop_file_system under the channel folder. The task's "home"
 * row at Unfiled/Tasks/<title> is created by PostHog's FileSystemSyncMixin on
 * task save; these rows are additional filings that posthog preserves via the
 * remaining>0 check on delete.
 */
@injectable()
export class ChannelTasksService {
  constructor(
    @inject(DESKTOP_FS_CLIENT)
    private readonly fs: DesktopFsClient,
  ) {}

  async list(channelId: string): Promise<ChannelTaskRecord[]> {
    const channelPath = await this.channelPath(channelId);
    const entries = await this.listUnderParent(channelPath);
    return entries
      .filter((e) => !!e.ref)
      .map((e) => toRecord(e, channelId))
      .sort((a, b) => b.createdAt - a.createdAt);
  }

  async file(input: {
    channelId: string;
    taskId: string;
    taskTitle: string;
  }): Promise<ChannelTaskRecord> {
    const targetChannelPath = await this.channelPath(input.channelId);
    const targetPath = `${targetChannelPath}/${sanitizeSegment(input.taskTitle)}`;

    const allRows = await this.listByRef(input.taskId);
    const homeRow = allRows.find((r) => r.path.startsWith(HOME_FOLDER));
    const channelRows = allRows.filter((r) => r !== homeRow);

    // Already at the target channel — nothing to do.
    const atTarget = channelRows.find((r) =>
      r.path.startsWith(`${targetChannelPath}/`),
    );
    if (atTarget) return toRecord(atTarget, input.channelId);

    // Ensure the home row exists before touching channel rows. Tasks created
    // before posthog's FileSystemSyncMixin landed have no home row; without
    // one, mutating the only channel row would cascade into a soft-delete of
    // the task itself.
    if (!homeRow) {
      await this.createRow(
        `${HOME_FOLDER}/${sanitizeSegment(input.taskTitle)}`,
        input.taskId,
      );
    }

    // If the task is already in some other channel, move that row to the
    // target instead of creating a duplicate. Defensive: drop any extra
    // channel rows (shouldn't normally exist with this invariant).
    if (channelRows.length > 0) {
      const [moved, ...extras] = channelRows;
      const movedRow = await this.moveRow(moved.id, targetPath);
      for (const extra of extras) await this.unfile(extra.id);
      return toRecord(movedRow, input.channelId);
    }

    const created = await this.createRow(targetPath, input.taskId);
    return toRecord(created, input.channelId);
  }

  async unfile(id: string): Promise<void> {
    const res = await this.fs.fetch(`${encodeURIComponent(id)}/`, {
      method: "DELETE",
    });
    if (!res.ok && res.status !== 404) {
      throw new Error(`Failed to unfile task (${res.status})`);
    }
  }

  private async listUnderParent(parentPath: string): Promise<FsEntry[]> {
    const res = await this.fs.fetch(
      `?parent=${encodeURIComponent(parentPath)}&type=${TASK_TYPE}`,
    );
    if (!res.ok)
      throw new Error(`Failed to list channel tasks (${res.status})`);
    const page = (await res.json()) as { results: FsEntry[] };
    return page.results;
  }

  private async listByRef(taskId: string): Promise<FsEntry[]> {
    const res = await this.fs.fetch(
      `?type=${TASK_TYPE}&ref=${encodeURIComponent(taskId)}`,
    );
    if (!res.ok) throw new Error(`Failed to list task rows (${res.status})`);
    const page = (await res.json()) as { results: FsEntry[] };
    return page.results;
  }

  private async createRow(path: string, taskId: string): Promise<FsEntry> {
    const res = await this.fs.fetch("", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path,
        type: TASK_TYPE,
        ref: taskId,
        href: `/tasks/${taskId}`,
      }),
    });
    if (!res.ok) throw new Error(`Failed to file task (${res.status})`);
    return (await res.json()) as FsEntry;
  }

  private async moveRow(id: string, newPath: string): Promise<FsEntry> {
    const res = await this.fs.fetch(`${encodeURIComponent(id)}/move/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_path: newPath }),
    });
    if (!res.ok) throw new Error(`Failed to move task row (${res.status})`);
    return (await res.json()) as FsEntry;
  }

  private async channelPath(channelId: string): Promise<string> {
    const entry = await this.fs.getEntry<FsEntry>(channelId, "channel");
    if (!entry) throw new Error("Channel not found");
    return entry.path;
  }
}

function toRecord(entry: FsEntry, channelId: string): ChannelTaskRecord {
  return {
    id: entry.id,
    channelId,
    taskId: entry.ref ?? "",
    createdAt: toEpoch(entry.created_at),
  };
}

function sanitizeSegment(name: string): string {
  const cleaned = name.replace(/\//g, " ").replace(/\s+/g, " ").trim();
  return cleaned || "Untitled";
}

function toEpoch(iso?: string): number {
  if (!iso) return Date.now();
  const t = Date.parse(iso);
  return Number.isNaN(t) ? Date.now() : t;
}

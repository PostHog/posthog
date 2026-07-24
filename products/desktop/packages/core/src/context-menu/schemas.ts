import { z } from "zod";

export const taskContextMenuInput = z.object({
  taskTitle: z.string(),
  worktreePath: z.string().optional(),
  folderPath: z.string().optional(),
  isPinned: z.boolean().optional(),
  isSuspended: z.boolean().optional(),
  canStop: z.boolean().optional(),
  isInCommandCenter: z.boolean().optional(),
  hasEmptyCommandCenterCell: z.boolean().optional(),
  // Top-level desktop_file_system channels available as "File to…" targets.
  // Omit (or pass empty) to hide the submenu entirely.
  channels: z.array(z.object({ id: z.string(), name: z.string() })).optional(),
});

export const bulkTaskContextMenuInput = z.object({
  taskCount: z.number().int().min(2),
});

export const archivedTaskContextMenuInput = z.object({
  taskTitle: z.string(),
});

export const folderContextMenuInput = z.object({
  folderName: z.string(),
  folderPath: z.string().optional(),
});

export const tabContextMenuInput = z.object({
  canClose: z.boolean(),
  filePath: z.string().optional(),
});

export const fileContextMenuInput = z.object({
  filePath: z.string(),
  showCollapseAll: z.boolean().optional(),
});

const externalAppAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("open-in-app"), appId: z.string() }),
  z.object({ type: z.literal("copy-path") }),
]);

const taskAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("rename") }),
  z.object({ type: z.literal("pin") }),
  z.object({ type: z.literal("suspend") }),
  z.object({ type: z.literal("stop") }),
  z.object({ type: z.literal("archive") }),
  z.object({ type: z.literal("archive-prior") }),
  z.object({ type: z.literal("delete") }),
  z.object({ type: z.literal("add-to-command-center") }),
  z.object({ type: z.literal("external-app"), action: externalAppAction }),
  z.object({ type: z.literal("file-to-channel"), channelId: z.string() }),
]);

const bulkTaskAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("archive") }),
]);

const archivedTaskAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("restore") }),
  z.object({ type: z.literal("delete") }),
]);

const folderAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("remove") }),
  z.object({ type: z.literal("external-app"), action: externalAppAction }),
]);

const tabAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("close") }),
  z.object({ type: z.literal("close-others") }),
  z.object({ type: z.literal("close-right") }),
  z.object({ type: z.literal("external-app"), action: externalAppAction }),
]);

const fileAction = z.discriminatedUnion("type", [
  z.object({ type: z.literal("collapse-all") }),
  z.object({ type: z.literal("external-app"), action: externalAppAction }),
]);

const splitDirection = z.enum(["left", "right", "up", "down"]);

export const taskContextMenuOutput = z.object({
  action: taskAction.nullable(),
});
export const bulkTaskContextMenuOutput = z.object({
  action: bulkTaskAction.nullable(),
});
export const archivedTaskContextMenuOutput = z.object({
  action: archivedTaskAction.nullable(),
});
export const folderContextMenuOutput = z.object({
  action: folderAction.nullable(),
});
export const tabContextMenuOutput = z.object({ action: tabAction.nullable() });
export const fileContextMenuOutput = z.object({
  action: fileAction.nullable(),
});
export const splitContextMenuOutput = z.object({
  direction: splitDirection.nullable(),
});

export type TaskContextMenuInput = z.infer<typeof taskContextMenuInput>;
export type BulkTaskContextMenuInput = z.infer<typeof bulkTaskContextMenuInput>;
export type ArchivedTaskContextMenuInput = z.infer<
  typeof archivedTaskContextMenuInput
>;
export type FolderContextMenuInput = z.infer<typeof folderContextMenuInput>;
export type TabContextMenuInput = z.infer<typeof tabContextMenuInput>;
export type FileContextMenuInput = z.infer<typeof fileContextMenuInput>;

export type ExternalAppAction = z.infer<typeof externalAppAction>;
export type TaskAction = z.infer<typeof taskAction>;
export type BulkTaskAction = z.infer<typeof bulkTaskAction>;
export type ArchivedTaskAction = z.infer<typeof archivedTaskAction>;
export type FolderAction = z.infer<typeof folderAction>;
export type TabAction = z.infer<typeof tabAction>;
export type FileAction = z.infer<typeof fileAction>;
export type SplitDirection = z.infer<typeof splitDirection>;

export const confirmDeleteTaskInput = z.object({
  taskTitle: z.string(),
  hasWorktree: z.boolean(),
});

export const confirmDeleteTaskOutput = z.object({
  confirmed: z.boolean(),
});

export const confirmDeleteArchivedTaskInput = z.object({
  taskTitle: z.string(),
});

export const confirmDeleteArchivedTaskOutput = z.object({
  confirmed: z.boolean(),
});

export const confirmDeleteWorktreeInput = z.object({
  worktreePath: z.string(),
  linkedTaskCount: z.number(),
});

export const confirmDeleteWorktreeOutput = z.object({
  confirmed: z.boolean(),
});

export type ConfirmDeleteTaskInput = z.infer<typeof confirmDeleteTaskInput>;
export type ConfirmDeleteTaskResult = z.infer<typeof confirmDeleteTaskOutput>;
export type ConfirmDeleteArchivedTaskInput = z.infer<
  typeof confirmDeleteArchivedTaskInput
>;
export type ConfirmDeleteArchivedTaskResult = z.infer<
  typeof confirmDeleteArchivedTaskOutput
>;
export type ConfirmDeleteWorktreeInput = z.infer<
  typeof confirmDeleteWorktreeInput
>;
export type ConfirmDeleteWorktreeResult = z.infer<
  typeof confirmDeleteWorktreeOutput
>;

export type TaskContextMenuResult = z.infer<typeof taskContextMenuOutput>;
export type BulkTaskContextMenuResult = z.infer<
  typeof bulkTaskContextMenuOutput
>;
export type ArchivedTaskContextMenuResult = z.infer<
  typeof archivedTaskContextMenuOutput
>;
export type FolderContextMenuResult = z.infer<typeof folderContextMenuOutput>;
export type TabContextMenuResult = z.infer<typeof tabContextMenuOutput>;
export type FileContextMenuResult = z.infer<typeof fileContextMenuOutput>;
export type SplitContextMenuResult = z.infer<typeof splitContextMenuOutput>;

import { z } from "zod";

// A filing is the task's `channel` field on the tasks API, so the task id IS
// the record's identity — there is no separate row id.
export const channelTaskRecordSchema = z.object({
  channelId: z.string(),
  taskId: z.string(),
  createdAt: z.number(),
});
export type ChannelTaskRecord = z.infer<typeof channelTaskRecordSchema>;

export const listChannelTasksInput = z.object({
  channelId: z.string().min(1),
});

export const fileChannelTaskInput = z.object({
  channelId: z.string().min(1),
  taskId: z.string().min(1),
});

export const unfileChannelTaskInput = z.object({ taskId: z.string().min(1) });

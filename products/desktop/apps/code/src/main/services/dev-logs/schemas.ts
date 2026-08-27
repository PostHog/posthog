import { z } from "zod";

export const logEntrySchema = z.object({
  id: z.number(),
  level: z.string(),
  scope: z.string().optional(),
  message: z.string(),
  capturedAt: z.number(),
  source: z.enum(["main", "renderer"]),
});

export type LogEntry = z.infer<typeof logEntrySchema>;

export const logsSnapshotSchema = z.object({
  entries: z.array(logEntrySchema),
});

export type LogsSnapshot = z.infer<typeof logsSnapshotSchema>;

export const DevLogsEvent = {
  Entry: "entry",
} as const;

export interface DevLogsEvents {
  [DevLogsEvent.Entry]: LogEntry;
}

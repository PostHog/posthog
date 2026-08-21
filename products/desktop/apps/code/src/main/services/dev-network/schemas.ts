import { z } from "zod";

export const networkRequestSchema = z.object({
  id: z.number(),
  method: z.string(),
  url: z.string(),
  host: z.string(),
  origin: z.enum(["main", "renderer"]),
  status: z.number().nullable(),
  ok: z.boolean(),
  durationMs: z.number(),
  startedAt: z.number(),
  bytes: z.number().nullable(),
  error: z.string().optional(),
});

export type NetworkRequest = z.infer<typeof networkRequestSchema>;

export const networkSnapshotSchema = z.object({
  requests: z.array(networkRequestSchema),
});

export type NetworkSnapshot = z.infer<typeof networkSnapshotSchema>;

export const networkSimSchema = z.object({
  offline: z.boolean(),
  slowDelayMs: z.number().min(0).max(10_000),
});

export type NetworkSim = z.infer<typeof networkSimSchema>;

export const DevNetworkEvent = {
  Request: "request",
  SimChanged: "sim-changed",
} as const;

export interface DevNetworkEvents {
  [DevNetworkEvent.Request]: NetworkRequest;
  [DevNetworkEvent.SimChanged]: NetworkSim;
}

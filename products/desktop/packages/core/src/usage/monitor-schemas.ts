import { z } from "zod";
import { type UsageOutput, usageOutput } from "./schemas";

export const USAGE_THRESHOLDS = [50, 75, 90, 100] as const;
export type UsageThreshold = (typeof USAGE_THRESHOLDS)[number];

export const thresholdCrossedEvent = z.object({
  bucket: z.enum(["burst", "sustained"]),
  threshold: z.union([
    z.literal(50),
    z.literal(75),
    z.literal(90),
    z.literal(100),
  ]),
  usedPercent: z.number(),
  resetAt: z.string().datetime(),
  isPro: z.boolean(),
  userIsActive: z.boolean(),
});

export type ThresholdCrossedEvent = z.infer<typeof thresholdCrossedEvent>;

export const usageSnapshotOutput = usageOutput.nullable();
export type UsageSnapshot = UsageOutput | null;

export const UsageMonitorEvent = {
  ThresholdCrossed: "threshold-crossed",
  UsageUpdated: "usage-updated",
} as const;

export interface UsageMonitorEvents {
  [UsageMonitorEvent.ThresholdCrossed]: ThresholdCrossedEvent;
  [UsageMonitorEvent.UsageUpdated]: UsageOutput;
}

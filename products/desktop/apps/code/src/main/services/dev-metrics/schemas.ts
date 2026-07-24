import { z } from "zod";

export const processSampleSchema = z.object({
  pid: z.number(),
  type: z.string(),
  name: z.string().optional(),
  cpuPercent: z.number(),
  memoryMb: z.number(),
});

export const metricsSampleSchema = z.object({
  capturedAt: z.number(),
  totalCpuPercent: z.number(),
  totalMemoryMb: z.number(),
  heapUsedMb: z.number(),
  heapTotalMb: z.number(),
  loopLagMs: z.number(),
  loopLagMaxMs: z.number(),
  processes: z.array(processSampleSchema),
});

export type ProcessSample = z.infer<typeof processSampleSchema>;
export type MetricsSample = z.infer<typeof metricsSampleSchema>;

export const DevMetricsEvent = {
  Sample: "sample",
} as const;

export interface DevMetricsEvents {
  [DevMetricsEvent.Sample]: MetricsSample;
}

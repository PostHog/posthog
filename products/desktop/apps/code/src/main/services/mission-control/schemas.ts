import { z } from "zod";

export const missionControlStateSchema = z.object({
  active: z.boolean(),
});

export type MissionControlState = z.infer<typeof missionControlStateSchema>;

const observedWindowSchema = z.object({
  ownerName: z.string(),
  layer: z.number(),
  bounds: z.object({
    x: z.number(),
    y: z.number(),
    width: z.number(),
    height: z.number(),
  }),
  /** Milliseconds from the start of the recording. */
  firstSeenMs: z.number(),
  lastSeenMs: z.number(),
});

// A recording rather than a one-shot dump: Mission Control is modal, so
// sampling has to start before it opens.
export const missionControlProbeSchema = z.object({
  available: z.boolean(),
  durationMs: z.number(),
  detectedAtMs: z.array(z.number()),
  appeared: z.array(observedWindowSchema),
});

export type MissionControlProbe = z.infer<typeof missionControlProbeSchema>;
export type ObservedWindow = z.infer<typeof observedWindowSchema>;

export const MissionControlServiceEvent = {
  StateChanged: "state-changed",
} as const;

export interface MissionControlServiceEvents {
  [MissionControlServiceEvent.StateChanged]: MissionControlState;
}

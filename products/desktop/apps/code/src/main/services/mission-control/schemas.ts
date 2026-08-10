import { z } from "zod";

/** Whether the app window is currently sitting in macOS Mission Control. */
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

/**
 * A recording of what the window list did, used to re-derive the detection
 * heuristic when a macOS release breaks it.
 *
 * A recording rather than a one-shot dump because Mission Control is a modal
 * overlay: the app is unclickable while it is open, so sampling has to start
 * beforehand. The timings then let one recording cover several gestures, which is
 * how a false positive gets told from the real thing.
 */
export const missionControlProbeSchema = z.object({
  /** False on non-macOS, or when the CoreGraphics binding failed to load. */
  available: z.boolean(),
  durationMs: z.number(),
  /** Every moment the current heuristic matched. */
  detectedAtMs: z.array(z.number()),
  /** Windows that were not there when sampling started. Unfiltered by owner. */
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

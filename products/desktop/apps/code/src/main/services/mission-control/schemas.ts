import { z } from "zod";

/** Whether the app window is currently sitting in macOS Mission Control. */
export const missionControlStateSchema = z.object({
  active: z.boolean(),
});

export type MissionControlState = z.infer<typeof missionControlStateSchema>;

const cgWindowSchema = z.object({
  ownerName: z.string(),
  ownerPid: z.number(),
  layer: z.number(),
  bounds: z.object({
    x: z.number(),
    y: z.number(),
    width: z.number(),
    height: z.number(),
  }),
});

/**
 * A window plus when it was on screen during the recording. The timings are what
 * make one recording able to cover several gestures: open Mission Control, then
 * app-switch, then hover the Dock, and each gesture's windows separate out by
 * when they came and went.
 */
const observedWindowSchema = cgWindowSchema.extend({
  /** Milliseconds from the start of the recording to first sighting. */
  firstSeenMs: z.number(),
  lastSeenMs: z.number(),
});

/**
 * Result of watching the window list for a few seconds, exposed through the dev
 * toolbar so the detection heuristic can be checked against a real macOS
 * release.
 *
 * It has to be a recording rather than a one-shot dump: Mission Control is a
 * modal system overlay, so there is no way to click anything in the app while it
 * is open. The only way to see the window list in that state is to start
 * sampling first and open Mission Control during the window.
 *
 * Nothing here filters by owner. If a later macOS moved the surface off the Dock
 * process — plausible since Stage Manager introduced WindowManager — a
 * Dock-only view would hide the very row that identifies it.
 */
export const missionControlProbeSchema = z.object({
  /** False on non-macOS, or when the CoreGraphics binding failed to load. */
  available: z.boolean(),
  durationMs: z.number(),
  /** Milliseconds at which the current heuristic first and last matched. */
  detectedAtMs: z.array(z.number()),
  /** Windows that showed up after sampling started — the interesting set. */
  appeared: z.array(observedWindowSchema),
  /** Windows present at the start that went away at some point. */
  disappeared: z.array(cgWindowSchema),
  /** How many windows were on screen when sampling started, for context. */
  baselineCount: z.number(),
  /** Our own process id, so our windows can be picked out of the list. */
  ownPid: z.number(),
});

export type MissionControlProbe = z.infer<typeof missionControlProbeSchema>;
export type ObservedWindow = z.infer<typeof observedWindowSchema>;

export const MissionControlServiceEvent = {
  StateChanged: "state-changed",
} as const;

export interface MissionControlServiceEvents {
  [MissionControlServiceEvent.StateChanged]: MissionControlState;
}

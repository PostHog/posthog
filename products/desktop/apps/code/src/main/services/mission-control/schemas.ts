import { z } from "zod";

/** Whether the app window is currently sitting in macOS Mission Control. */
export const missionControlStateSchema = z.object({
  active: z.boolean(),
});

export type MissionControlState = z.infer<typeof missionControlStateSchema>;

const cgWindowSchema = z.object({
  ownerName: z.string(),
  layer: z.number(),
  bounds: z.object({
    x: z.number(),
    y: z.number(),
    width: z.number(),
    height: z.number(),
  }),
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
  /** True if the current heuristic matched at any point during the recording. */
  detected: z.boolean(),
  /** Windows that showed up after sampling started — the interesting set. */
  appeared: z.array(cgWindowSchema),
  /** Windows present at the start that went away at some point. */
  disappeared: z.array(cgWindowSchema),
  /** How many windows were on screen when sampling started, for context. */
  baselineCount: z.number(),
});

export type MissionControlProbe = z.infer<typeof missionControlProbeSchema>;

export const MissionControlServiceEvent = {
  StateChanged: "state-changed",
} as const;

export interface MissionControlServiceEvents {
  [MissionControlServiceEvent.StateChanged]: MissionControlState;
}

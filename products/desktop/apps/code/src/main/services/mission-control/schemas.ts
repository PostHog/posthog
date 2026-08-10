import { z } from "zod";

/** Whether the app window is currently sitting in macOS Mission Control. */
export const missionControlStateSchema = z.object({
  active: z.boolean(),
});

export type MissionControlState = z.infer<typeof missionControlStateSchema>;

/**
 * Raw Dock-owned window rows, exposed through the dev toolbar so the detection
 * heuristic can be validated against a real macOS release: the predicate keys
 * off undocumented Dock window geometry, so the only way to confirm it still
 * holds is to diff a dump taken with Mission Control open against one without.
 */
export const dockWindowDumpSchema = z.object({
  /** False on non-macOS, or when the CoreGraphics binding failed to load. */
  available: z.boolean(),
  /** What the heuristic makes of this sample. */
  detected: z.boolean(),
  windows: z.array(
    z.object({
      ownerName: z.string(),
      layer: z.number(),
      bounds: z.object({
        x: z.number(),
        y: z.number(),
        width: z.number(),
        height: z.number(),
      }),
    }),
  ),
});

export type DockWindowDump = z.infer<typeof dockWindowDumpSchema>;

export const MissionControlServiceEvent = {
  StateChanged: "state-changed",
} as const;

export interface MissionControlServiceEvents {
  [MissionControlServiceEvent.StateChanged]: MissionControlState;
}

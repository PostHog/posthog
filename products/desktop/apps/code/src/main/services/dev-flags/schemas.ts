import { z } from "zod";

export const devFlagsSchema = z.object({
  devMode: z.boolean(),
});

export type DevFlags = z.infer<typeof devFlagsSchema>;

export const DEFAULT_DEV_FLAGS: DevFlags = {
  devMode: false,
};

export const DevFlagsEvent = {
  Changed: "changed",
} as const;

export interface DevFlagsEvents {
  [DevFlagsEvent.Changed]: DevFlags;
}

import { z } from "zod";

export const devToastInput = z.object({
  variant: z.enum(["info", "error"]),
  message: z.string(),
});

export const devToastSchema = z.object({
  id: z.number(),
  variant: z.enum(["info", "error"]),
  message: z.string(),
});

export type DevToast = z.infer<typeof devToastSchema>;

export const DevActionsEvent = {
  Toast: "toast",
} as const;

export interface DevActionsEvents {
  [DevActionsEvent.Toast]: DevToast;
}

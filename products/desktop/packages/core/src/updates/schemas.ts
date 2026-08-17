import { z } from "zod";

export const isEnabledOutput = z.object({
  enabled: z.boolean(),
});

export const checkErrorCode = z.enum(["already_checking", "disabled"]);
export type CheckErrorCode = z.infer<typeof checkErrorCode>;

export const checkForUpdatesOutput = z.object({
  success: z.boolean(),
  errorMessage: z.string().optional(),
  errorCode: checkErrorCode.optional(),
});

export const updatesStatusOutput = z.object({
  checking: z.boolean(),
  downloading: z.boolean().optional(),
  available: z.boolean().optional(),
  upToDate: z.boolean().optional(),
  updateReady: z.boolean().optional(),
  installing: z.boolean().optional(),
  version: z.string().optional(),
  availableVersion: z.string().optional(),
  releaseNotes: z.string().nullable().optional(),
  releaseDate: z.string().optional(),
  downloadPercent: z.number().optional(),
  bytesPerSecond: z.number().optional(),
  downloadSizeBytes: z.number().nullable().optional(),
  error: z.string().optional(),
});

export const installUpdateOutput = z.object({
  installed: z.boolean(),
});

export type IsEnabledOutput = z.infer<typeof isEnabledOutput>;

export type CheckForUpdatesOutput = z.infer<typeof checkForUpdatesOutput>;
export type InstallUpdateOutput = z.infer<typeof installUpdateOutput>;

export const UpdatesEvent = {
  Ready: "ready",
  Status: "status",
  CheckFromMenu: "check-from-menu",
} as const;

export type UpdatesStatusPayload = z.infer<typeof updatesStatusOutput>;

export type UpdateReadyPayload = {
  version: string | null;
};

export interface UpdatesEvents {
  [UpdatesEvent.Ready]: UpdateReadyPayload;
  [UpdatesEvent.Status]: UpdatesStatusPayload;
  [UpdatesEvent.CheckFromMenu]: true;
}

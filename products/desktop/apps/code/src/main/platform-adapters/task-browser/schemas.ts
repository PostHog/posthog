import { z } from "zod";

export const browserTabKindSchema = z.enum(["browser", "preview"]);
export type BrowserTabKind = z.infer<typeof browserTabKindSchema>;

export const registerTabInput = z.object({
  browserId: z.string().min(1).max(200),
  taskId: z.string().min(1).max(200),
  webContentsId: z.number().int().positive(),
  kind: browserTabKindSchema,
});
export type RegisterTabInput = z.infer<typeof registerTabInput>;

export const openRequestSchema = z.object({
  taskId: z.string(),
  browserId: z.string(),
  url: z.string(),
});
export type OpenRequest = z.infer<typeof openRequestSchema>;

export const permissionKindSchema = z.enum([
  "site",
  "sensitive-action",
  "sign-in",
  "full-cdp",
]);
export type PermissionKind = z.infer<typeof permissionKindSchema>;

export const permissionDecisionSchema = z.enum([
  "allow-once",
  "allow-task",
  "allow-always",
  "deny",
  "block",
]);
export type PermissionDecision = z.infer<typeof permissionDecisionSchema>;

export const permissionRequestSchema = z.object({
  requestId: z.string(),
  taskId: z.string(),
  kind: permissionKindSchema,
  origin: z.string(),
  detail: z.string(),
});
export type PermissionRequest = z.infer<typeof permissionRequestSchema>;

export const permissionResponseInput = z.object({
  requestId: z.string().min(1).max(200),
  decision: permissionDecisionSchema,
});

export const sitePolicySchema = z.enum(["allow", "block"]);
export type SitePolicy = z.infer<typeof sitePolicySchema>;

export const browserSettingsSchema = z.object({
  sites: z.record(z.string(), sitePolicySchema),
  fullCdpAccess: z.boolean(),
});
export type BrowserSettings = z.infer<typeof browserSettingsSchema>;

export const setSitePolicyInput = z.object({
  origin: z.string().min(1).max(500),
  policy: sitePolicySchema.nullable(),
});

export const closeRequestSchema = z.object({
  taskId: z.string(),
  browserId: z.string(),
});
export type CloseRequest = z.infer<typeof closeRequestSchema>;

export const TaskBrowserEvent = {
  OpenRequest: "open-request",
  CloseRequest: "close-request",
  PermissionRequest: "permission-request",
  PermissionSettled: "permission-settled",
} as const;

export interface TaskBrowserEvents {
  [TaskBrowserEvent.OpenRequest]: OpenRequest;
  [TaskBrowserEvent.CloseRequest]: CloseRequest;
  [TaskBrowserEvent.PermissionRequest]: PermissionRequest;
  [TaskBrowserEvent.PermissionSettled]: { requestId: string };
}

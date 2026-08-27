import { z } from "zod";
import { cloudRegion, type oAuthTokenResponse } from "./oauth.schemas";

export const authStatusSchema = z.enum([
  "anonymous",
  "restoring",
  "authenticated",
]);
export type AuthStatus = z.infer<typeof authStatusSchema>;

export const orgProjectsSchema = z.object({
  orgName: z.string(),
  projects: z.array(z.object({ id: z.number(), name: z.string() })),
});
export type OrgProjects = z.infer<typeof orgProjectsSchema>;

export const orgProjectsMapSchema = z.record(z.string(), orgProjectsSchema);
export type OrgProjectsMap = z.infer<typeof orgProjectsMapSchema>;

export function flattenProjectIds(map: OrgProjectsMap): number[] {
  return Object.values(map).flatMap((org) => org.projects.map((p) => p.id));
}

export function findOrgForProject(
  map: OrgProjectsMap,
  projectId: number,
  preferredOrgId: string | null,
): string | null {
  if (
    preferredOrgId &&
    map[preferredOrgId]?.projects.some((p) => p.id === projectId)
  ) {
    return preferredOrgId;
  }
  for (const [orgId, org] of Object.entries(map)) {
    if (org.projects.some((p) => p.id === projectId)) {
      return orgId;
    }
  }
  return null;
}

export function pickInitialProjectId(args: {
  orgProjectsMap: OrgProjectsMap;
  currentOrgId: string | null;
  lastSelectedOrgId: string | null;
  preferredProjectId: number | null;
}): number | null {
  const {
    orgProjectsMap,
    currentOrgId,
    lastSelectedOrgId,
    preferredProjectId,
  } = args;

  const allProjectIds = flattenProjectIds(orgProjectsMap);
  if (preferredProjectId && allProjectIds.includes(preferredProjectId)) {
    return preferredProjectId;
  }

  const fromCurrentOrg = currentOrgId
    ? orgProjectsMap[currentOrgId]?.projects[0]?.id
    : undefined;
  if (fromCurrentOrg !== undefined) return fromCurrentOrg;

  const fromLastOrg = lastSelectedOrgId
    ? orgProjectsMap[lastSelectedOrgId]?.projects[0]?.id
    : undefined;
  if (fromLastOrg !== undefined) return fromLastOrg;

  return allProjectIds[0] ?? null;
}

export const desktopAccessReasonSchema = z.enum([
  "startup_plan",
  "prepaid_credits",
]);
export type DesktopAccessReason = z.infer<typeof desktopAccessReasonSchema>;

export const desktopAccessResponseSchema = z.union([
  z.object({ allowed: z.literal(true), reason: z.null() }),
  z.object({
    allowed: z.literal(false),
    reason: desktopAccessReasonSchema.nullable(),
  }),
]);

export const desktopAccessSchema = z.discriminatedUnion("status", [
  z.object({
    projectId: z.number().nullable(),
    status: z.literal("unchecked"),
    reason: z.null(),
  }),
  z.object({
    projectId: z.number().nullable(),
    status: z.literal("checking"),
    reason: z.null(),
  }),
  z.object({
    projectId: z.number(),
    status: z.literal("allowed"),
    reason: z.null(),
  }),
  z.object({
    projectId: z.number(),
    status: z.literal("blocked"),
    reason: desktopAccessReasonSchema.nullable(),
  }),
  z.object({
    projectId: z.number().nullable(),
    status: z.literal("error"),
    reason: z.null(),
  }),
]);
export type DesktopAccess = z.infer<typeof desktopAccessSchema>;

export const authStateSchema = z.object({
  status: authStatusSchema,
  bootstrapComplete: z.boolean(),
  cloudRegion: cloudRegion.nullable(),
  orgProjectsMap: orgProjectsMapSchema,
  currentOrgId: z.string().nullable(),
  currentProjectId: z.number().nullable(),
  desktopAccess: desktopAccessSchema,
  needsScopeReauth: z.boolean(),
  sessionType: z.enum(["persistent", "impersonated"]).nullable(),
  sessionExpiresAt: z.number().nullable(),
  sessionEndReason: z.enum(["impersonation_expired"]).nullable().optional(),
});
export type AuthState = z.infer<typeof authStateSchema>;

export const loginInput = z.object({
  region: cloudRegion,
});
export type LoginInput = z.infer<typeof loginInput>;

export const loginOutput = z.object({
  state: authStateSchema,
});
export type LoginOutput = z.infer<typeof loginOutput>;

export const selectProjectInput = z.object({
  projectId: z.number(),
});

export const switchOrgInput = z.object({
  orgId: z.string().min(1),
});
export type SwitchOrgInput = z.infer<typeof switchOrgInput>;

export const validAccessTokenOutput = z.object({
  accessToken: z.string(),
  apiHost: z.string(),
});
export type ValidAccessTokenOutput = z.infer<typeof validAccessTokenOutput>;

export const AuthServiceEvent = {
  StateChanged: "state-changed",
} as const;

export interface AuthServiceEvents {
  [AuthServiceEvent.StateChanged]: AuthState;
}

export type AuthTokenResponse = z.infer<typeof oAuthTokenResponse>;

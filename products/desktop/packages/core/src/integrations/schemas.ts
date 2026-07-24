import { z } from "zod";

export const cloudRegion = z.enum(["us", "eu", "dev"]);
export type CloudRegion = z.infer<typeof cloudRegion>;

export const startIntegrationFlowInput = z.object({
  region: cloudRegion,
  projectId: z.number(),
});
export type StartIntegrationFlowInput = z.infer<
  typeof startIntegrationFlowInput
>;

/**
 * Generic integration flow input: any OAuth `kind` PostHog supports. The per-kind routers
 * (linear/slack/github) keep the narrower input above; this one drives the generic starter so
 * new OAuth sources need no dedicated router.
 */
export const startGenericIntegrationFlowInput = z.object({
  kind: z.string(),
  region: cloudRegion,
  projectId: z.number(),
});
export type StartGenericIntegrationFlowInput = z.infer<
  typeof startGenericIntegrationFlowInput
>;

export const startIntegrationFlowOutput = z.object({
  success: z.boolean(),
  error: z.string().optional(),
});
export type StartIntegrationFlowOutput = z.infer<
  typeof startIntegrationFlowOutput
>;

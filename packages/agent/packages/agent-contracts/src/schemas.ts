import { z } from "zod";

const spaceGoalPeriodSchema = z.enum(["day", "week", "month"]);
const spaceGoalDirectionSchema = z.enum(["at_least", "at_most"]);

export const spaceGoalInputSchema = z.object({
  statement: z.string().trim().min(1).max(2000),
  period: spaceGoalPeriodSchema,
  direction: spaceGoalDirectionSchema,
  target: z.string().max(64).nullish(),
  deadline: z.iso.date().nullish(),
  insight_short_id: z.string().max(64).nullish(),
});

export const spaceFeatureInputSchema = z.object({
  name: z.string().trim().min(1).max(200),
  description: z.string().max(2000).optional(),
  flag_key: z.string().max(400).nullish(),
});

const repositorySchema = z.string().max(255).nullish();

export const spaceSetupInputSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("goal"),
    goal: spaceGoalInputSchema,
    repository: repositorySchema,
  }),
  z.object({
    kind: z.literal("feature"),
    feature: spaceFeatureInputSchema,
    repository: repositorySchema,
  }),
]);

export const spaceSetupStartedSchema = z.object({ task_id: z.uuid() });

export type SpaceGoalPeriod = z.infer<typeof spaceGoalPeriodSchema>;
export type SpaceGoalDirection = z.infer<typeof spaceGoalDirectionSchema>;
export type SpaceGoalInput = z.infer<typeof spaceGoalInputSchema>;
export type SpaceFeatureInput = z.infer<typeof spaceFeatureInputSchema>;
export type SpaceSetupInput = z.infer<typeof spaceSetupInputSchema>;
export type SpaceSetupKind = SpaceSetupInput["kind"];
export type SpaceSetupStarted = z.infer<typeof spaceSetupStartedSchema>;

import { z } from "zod";

/**
 * The shapes behind Home's "groups of work" — the work a person already has in
 * PostHog, read back so the app can open on it instead of on a blank prompt.
 *
 * Everything here is normalized to camelCase and epoch-ms timestamps, the same
 * treatment DashboardsService gives canvases, so a Home section never handles a
 * raw API row.
 */

/** A feature flag the viewer could plausibly still be working on. */
export const homeFeatureFlagSchema = z.object({
  id: z.number(),
  key: z.string(),
  name: z.string(),
  active: z.boolean(),
  /** Percentage of users the flag is rolled out to, where the flag sets one. */
  rolloutPercentage: z.number().nullable(),
  /** The flag drives an experiment, so Home shows it as an experiment instead. */
  hasExperiment: z.boolean(),
  createdAt: z.number(),
  /** The viewer created this flag. */
  yours: z.boolean(),
  /** Name of the creator, where the backend knows one. */
  createdBy: z.string().nullable(),
});
export type HomeFeatureFlag = z.infer<typeof homeFeatureFlagSchema>;

/** Where an experiment is in its life, as Home talks about it. */
export const homeExperimentStageSchema = z.enum([
  "draft",
  "running",
  "paused",
  "concluded",
]);
export type HomeExperimentStage = z.infer<typeof homeExperimentStageSchema>;

/** An experiment the viewer created or is running. */
export const homeExperimentSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable(),
  featureFlagKey: z.string().nullable(),
  stage: homeExperimentStageSchema,
  startedAt: z.number().nullable(),
  endedAt: z.number().nullable(),
  /** Variant keys, in the order the experiment declares them. */
  variants: z.array(z.string()),
  yours: z.boolean(),
  createdBy: z.string().nullable(),
});
export type HomeExperiment = z.infer<typeof homeExperimentSchema>;

/** Everything Home prefetches in one round trip. */
export const homeWorkSchema = z.object({
  featureFlags: z.array(homeFeatureFlagSchema),
  experiments: z.array(homeExperimentSchema),
  /**
   * Groups that did not load — no scope, no product, or a failed request. Home
   * says so rather than showing an empty section that reads as "you have no
   * experiments".
   */
  unavailable: z.array(z.enum(["featureFlags", "experiments"])),
});
export type HomeWork = z.infer<typeof homeWorkSchema>;

export const homeWorkInput = z.object({
  /**
   * The viewer's user id, so the service can mark what is theirs. Absent while
   * the current user is still loading — everything comes back unmarked.
   */
  viewerId: z.number().nullish(),
  /** How many rows to keep per group. */
  limit: z.number().int().min(1).max(50).default(6),
});
export type HomeWorkInput = z.infer<typeof homeWorkInput>;

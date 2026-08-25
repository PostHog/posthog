import { z } from "zod";

export const platformStatusInput = z.object({
  region: z.enum(["us", "eu", "dev"]),
});

export const platformStatusOutput = z.object({
  status: z.enum([
    "operational",
    "degraded_performance",
    "partial_outage",
    "major_outage",
    "unknown",
  ]),
  statusPageUrl: z.string().url(),
});

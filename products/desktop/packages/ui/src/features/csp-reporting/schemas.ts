import { z } from "zod";
import { CSP_VIOLATION_NOTIFICATION } from "./identifiers";

/**
 * One entry of a Reporting API `application/reports+json` bundle, as produced by
 * `ReportingObserver` (or synthesized from a `SecurityPolicyViolationEvent`).
 * Kept loose on purpose: PostHog's `/report/` endpoint reads the fields it knows
 * and stores the rest as the raw report, so an unrecognized key is more useful
 * forwarded than dropped.
 *
 * @see https://developer.mozilla.org/en-US/docs/Web/API/CSPViolationReportBody
 */
export const cspViolationReportSchema = z.object({
  type: z.literal("csp-violation"),
  url: z.string().optional(),
  body: z.looseObject({
    documentURL: z.string().optional(),
    blockedURL: z.string().nullish(),
    effectiveDirective: z.string().optional(),
    disposition: z.string().optional(),
  }),
});

export type CspViolationReport = z.infer<typeof cspViolationReportSchema>;

/** Message the frame posts out; anything else on the channel is not ours. */
export const cspViolationNotificationSchema = z.object({
  method: z.literal(CSP_VIOLATION_NOTIFICATION),
  params: z.object({ report: cspViolationReportSchema }),
});

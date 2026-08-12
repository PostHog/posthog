import type { Contribution } from "@posthog/di/contribution";
import { inject, injectable } from "inversify";
import {
  ANALYTICS_TRACKER,
  type AnalyticsTracker,
} from "../../shell/analytics";
import { startCspViolationCollector } from "./cspViolationCollector";

/**
 * Forwards CSP violations from sandboxed frames to PostHog for the lifetime of
 * the renderer. Without this the only trace of a blocked script or stylesheet is
 * a console line in whatever window happened to be open, so an app that renders
 * blank for users looks fine from the outside.
 */
@injectable()
export class CspReportingContribution implements Contribution {
  constructor(
    @inject(ANALYTICS_TRACKER)
    private readonly analytics: AnalyticsTracker,
  ) {}

  start(): void {
    startCspViolationCollector({
      send: (reports) => this.analytics.reportCspViolations(reports),
    });
  }
}

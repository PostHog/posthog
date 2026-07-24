import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { injectable } from "inversify";
import {
  type BulkActionResult,
  buildSnoozeRequest,
  buildSuppressRequest,
  type DismissReportInput,
  tallySettledResults,
} from "./bulkActions";

@injectable()
export class InboxBulkActionService {
  private async runBulk(
    reportIds: string[],
    perReport: (reportId: string) => Promise<unknown>,
  ): Promise<BulkActionResult> {
    const results = await Promise.allSettled(reportIds.map(perReport));
    return tallySettledResults(results);
  }

  async suppressReports(
    client: PostHogAPIClient,
    reportIds: string[],
    dismissal?: DismissReportInput,
  ): Promise<BulkActionResult> {
    return this.runBulk(reportIds, (reportId) =>
      client.updateSignalReportState(reportId, buildSuppressRequest(dismissal)),
    );
  }

  async snoozeReports(
    client: PostHogAPIClient,
    reportIds: string[],
  ): Promise<BulkActionResult> {
    return this.runBulk(reportIds, (reportId) =>
      client.updateSignalReportState(reportId, buildSnoozeRequest()),
    );
  }

  async deleteReports(
    client: PostHogAPIClient,
    reportIds: string[],
  ): Promise<BulkActionResult> {
    return this.runBulk(reportIds, (reportId) =>
      client.deleteSignalReport(reportId),
    );
  }

  async reingestReports(
    client: PostHogAPIClient,
    reportIds: string[],
  ): Promise<BulkActionResult> {
    return this.runBulk(reportIds, (reportId) =>
      client.reingestSignalReport(reportId),
    );
  }
}

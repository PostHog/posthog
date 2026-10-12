import type {
  SignalReportsQueryParams,
  SignalReportsResponse,
} from "@posthog/shared/domain-types";
import { injectable } from "inversify";
import { buildSuggestedReviewerFilterParam } from "./reportFiltering";

@injectable()
export class InboxReportService {
  constructor(
    private readonly getCurrentUser: () => Promise<{ uuid: string }>,
    private readonly getSignalReports: (
      params: SignalReportsQueryParams,
    ) => Promise<SignalReportsResponse>,
  ) {}

  async listReports(
    params: SignalReportsQueryParams,
    reviewerFilter: string[] | null,
  ): Promise<SignalReportsResponse> {
    let reviewers = reviewerFilter;
    if (reviewers === null) {
      const user = await this.getCurrentUser();
      if (!user.uuid?.trim()) {
        throw new Error("Cannot load your user account. Try again.");
      }
      reviewers = [user.uuid];
    }

    return this.getSignalReports({
      ...params,
      suggested_reviewers: buildSuggestedReviewerFilterParam(reviewers),
    });
  }
}

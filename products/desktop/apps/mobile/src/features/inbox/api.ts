import { HttpError } from "@/features/tasks/api";
import { authedFetch, getBaseUrl, getProjectId } from "@/lib/api";
import { logger } from "@/lib/logger";
import type { DismissalReasonOptionValue } from "./constants";

const log = logger.scope("inbox-api");

import type {
  AvailableSuggestedReviewer,
  AvailableSuggestedReviewersResponse,
  CommitDiffResponse,
  ReportArtefact,
  SignalProcessingStateResponse,
  SignalReport,
  SignalReportArtefactsResponse,
  SignalReportSignalsResponse,
  SignalReportsQueryParams,
  SignalReportsResponse,
  SuggestedReviewerWriteEntry,
} from "./types";

export async function getSignalReports(
  params?: SignalReportsQueryParams,
): Promise<SignalReportsResponse> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const url = new URL(`${baseUrl}/api/projects/${projectId}/signals/reports/`);

  if (params?.limit != null) {
    url.searchParams.set("limit", String(params.limit));
  }
  if (params?.offset != null) {
    url.searchParams.set("offset", String(params.offset));
  }
  if (params?.status) {
    url.searchParams.set("status", params.status);
  }
  if (params?.ordering) {
    url.searchParams.set("ordering", params.ordering);
  }
  if (params?.source_product) {
    url.searchParams.set("source_product", params.source_product);
  }
  if (params?.suggested_reviewers) {
    url.searchParams.set("suggested_reviewers", params.suggested_reviewers);
  }
  if (params?.priority) {
    url.searchParams.set("priority", params.priority);
  }

  const response = await authedFetch(url.toString());

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch signal reports",
    );
  }

  const data = await response.json();
  return {
    results: data.results ?? [],
    count: data.count ?? data.results?.length ?? 0,
  };
}

export async function getSignalReport(
  reportId: string,
): Promise<SignalReport | null> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/`,
  );

  if (response.status === 404 || response.status === 403) {
    return null;
  }

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch signal report",
    );
  }

  return await response.json();
}

export async function getSignalProcessingState(): Promise<SignalProcessingStateResponse> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/processing_state/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch signal processing state",
    );
  }

  return await response.json();
}

export async function getAvailableSuggestedReviewers(
  query?: string,
): Promise<AvailableSuggestedReviewersResponse> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const url = new URL(
    `${baseUrl}/api/projects/${projectId}/signals/reports/available_reviewers/`,
  );

  if (query?.trim()) {
    url.searchParams.set("query", query.trim());
  }

  const response = await authedFetch(url.toString());

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Failed to fetch available suggested reviewers",
    );
  }

  // API returns a dict keyed by UUID: { "uuid": { name, email, github_login } }
  const data = await response.json();
  const results = Object.entries(data)
    .map(([uuid, value]) => {
      if (typeof value !== "object" || value === null) return null;
      const v = value as Record<string, unknown>;
      return {
        uuid,
        name: typeof v.name === "string" ? v.name : "",
        email: typeof v.email === "string" ? v.email : "",
        github_login: typeof v.github_login === "string" ? v.github_login : "",
      };
    })
    .filter((r): r is AvailableSuggestedReviewer => r !== null);

  return { results, count: results.length };
}

export async function getSignalReportArtefacts(
  reportId: string,
): Promise<SignalReportArtefactsResponse> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/artefacts/`,
  );

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    log.warn("Failed to fetch report artefacts", {
      reportId,
      status: response.status,
      body: body.slice(0, 500),
    });
    return { results: [], count: 0 };
  }

  const data = await response.json();
  const results: ReportArtefact[] = data.results ?? [];
  return { results, count: data.count ?? results.length };
}

/** Fetch a commit artefact's diff against its parent (lazily, on demand). */
export async function getCommitDiff(
  reportId: string,
  artefactId: string,
): Promise<CommitDiffResponse> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/artefacts/${artefactId}/diff/`,
  );

  if (!response.ok) {
    throw new HttpError(
      response.status,
      response.statusText,
      "Couldn’t load the diff",
    );
  }

  const data = await response.json();
  return {
    diff: typeof data.diff === "string" ? data.diff : "",
    truncated: data.truncated === true,
  };
}

/** Replace the content of a report artefact (full PUT, not a partial update). */
export async function updateSignalReportArtefact(
  reportId: string,
  artefactId: string,
  content: SuggestedReviewerWriteEntry[],
): Promise<void> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/artefacts/${artefactId}/`,
    {
      method: "PUT",
      body: JSON.stringify({ content }),
    },
  );

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new HttpError(
      response.status,
      response.statusText,
      errorText || "Failed to update suggested reviewers",
    );
  }
}

export async function getSignalReportSignals(
  reportId: string,
): Promise<SignalReportSignalsResponse> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/signals/`,
  );

  if (!response.ok) {
    log.warn("Failed to fetch report signals", {
      reportId,
      status: response.status,
    });
    return { signals: [] };
  }

  const data = await response.json();
  return { signals: data.signals ?? [] };
}

/** Resolve the repository associated with a signal report via its repo_selection artefact. */
export async function getReportRepository(
  reportId: string,
): Promise<string | null> {
  const { results } = await getSignalReportArtefacts(reportId);
  const repoArtefact = results.find((a) => a.type === "repo_selection");
  if (!repoArtefact) return null;

  let parsed: unknown = repoArtefact.content;
  if (typeof parsed === "string") {
    try {
      parsed = JSON.parse(parsed);
    } catch {
      return (parsed as string).toLowerCase();
    }
  }

  if (typeof parsed === "object" && parsed !== null) {
    const repo =
      (parsed as Record<string, unknown>).repository ??
      (parsed as Record<string, unknown>).repo;
    if (typeof repo === "string") return repo.toLowerCase();
  }

  return null;
}

export interface DismissSignalReportInput {
  reason: DismissalReasonOptionValue;
  note?: string;
}

export async function dismissSignalReport(
  reportId: string,
  input: DismissSignalReportInput,
): Promise<SignalReport> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/state/`,
    {
      method: "POST",
      body: JSON.stringify({
        state: "suppressed",
        dismissal_reason: input.reason,
        ...(input.note?.trim() ? { dismissal_note: input.note.trim() } : {}),
      }),
    },
  );

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new HttpError(
      response.status,
      response.statusText,
      errorText || "Failed to dismiss signal report",
    );
  }

  return await response.json();
}

/** Re-queue a dismissed report into the inbox via the `potential` transition. */
export async function restoreSignalReport(
  reportId: string,
): Promise<SignalReport> {
  const baseUrl = getBaseUrl();
  const projectId = getProjectId();

  const response = await authedFetch(
    `${baseUrl}/api/projects/${projectId}/signals/reports/${reportId}/state/`,
    {
      method: "POST",
      body: JSON.stringify({ state: "potential" }),
    },
  );

  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new HttpError(
      response.status,
      response.statusText,
      errorText || "Failed to restore signal report",
    );
  }

  return await response.json();
}

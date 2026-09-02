import type { GithubInstallRequestItem } from "@posthog/api-client/posthog-client";

export function hasPendingInstallRequest(
  requests: ReadonlyArray<GithubInstallRequestItem> | undefined,
): boolean {
  return requests?.some((request) => request.status === "pending") ?? false;
}

/**
 * Approved requests still worth a "Finish connecting" prompt. An approved request is durable
 * server state that outlives the connection it unblocked, so once its installation is linked in
 * PostHog it drops out here — otherwise the banner keeps offering "Finish connecting" next to an
 * already-connected surface. Requests without an installation id (never expected once approved)
 * stay visible rather than being hidden on a missing match.
 */
export function unlinkedApprovedRequests(
  requests: ReadonlyArray<GithubInstallRequestItem> | undefined,
  linkedInstallationIds: ReadonlyArray<string>,
): GithubInstallRequestItem[] {
  const linked = new Set(linkedInstallationIds);
  return (requests ?? []).filter(
    (request) =>
      request.status === "approved" &&
      (request.installation_id === null ||
        !linked.has(request.installation_id)),
  );
}

export function buildOrgOwnerMessage(installUrl: string): string {
  return `Can you approve the PostHog GitHub app for our organization? Open ${installUrl}, pick the organization, and approve the pending request.`;
}

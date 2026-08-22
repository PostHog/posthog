import type { GithubInstallRequestItem } from "@posthog/api-client/posthog-client";

export function hasPendingInstallRequest(
  requests: ReadonlyArray<GithubInstallRequestItem> | undefined,
): boolean {
  return requests?.some((request) => request.status === "pending") ?? false;
}

export function buildOrgOwnerMessage(installUrl: string): string {
  return `Can you approve the PostHog GitHub app for our organization? Open ${installUrl}, pick the organization, and approve the pending request.`;
}

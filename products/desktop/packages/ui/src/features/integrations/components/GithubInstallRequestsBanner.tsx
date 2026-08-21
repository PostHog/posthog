import type { GithubInstallRequestItem } from "@posthog/api-client/posthog-client";
import {
  buildOrgOwnerMessage,
  unlinkedApprovedRequests,
} from "@posthog/core/integrations/installRequests";
import { Button, Text } from "@posthog/quill";
import { useDismissGithubInstallRequest } from "@posthog/ui/features/integrations/useDismissGithubInstallRequest";
import { useGithubInstallRequests } from "@posthog/ui/features/integrations/useGithubInstallRequests";
import { useUserGithubIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { useCopy } from "@posthog/ui/primitives/useCopy";

interface GithubInstallRequestsBannerProps {
  /** Re-runs the surface's own connect flow once an owner has approved the install. */
  onFinishConnecting: () => void;
  isConnecting?: boolean;
}

/**
 * The "waiting for a GitHub org owner" state and its resolution. Rendering this keeps the
 * install-request list polling while anything is pending.
 */
export function GithubInstallRequestsBanner({
  onFinishConnecting,
  isConnecting = false,
}: GithubInstallRequestsBannerProps) {
  const { data } = useGithubInstallRequests();
  const { data: linkedInstallations, isSuccess: linkedInstallationsLoaded } =
    useUserGithubIntegrations();
  const dismiss = useDismissGithubInstallRequest();
  const { copied, copy } = useCopy();

  const requests = data?.results ?? [];
  const pending = requests.filter((r) => r.status === "pending");
  // Only surface approved requests once we know which installations are already linked.
  // An empty list while the query loads or after it fails would read as "nothing linked"
  // and offer "Finish connecting" for an install that is in fact already connected.
  const approved = linkedInstallationsLoaded
    ? unlinkedApprovedRequests(
        requests,
        (linkedInstallations ?? []).map(
          (integration) => integration.installation_id,
        ),
      )
    : [];
  const installUrl = data?.install_url ?? null;

  if (pending.length === 0 && approved.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2">
      {approved.map((request: GithubInstallRequestItem) => (
        <div
          key={request.id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-(--radius-2) border border-(--green-6) bg-(--green-2) px-3 py-2"
        >
          <Text size="sm">
            An organization owner approved the PostHog app for{" "}
            <span className="font-medium">
              {request.account_login ||
                request.github_login ||
                "your organization"}
            </span>
            . Finish connecting to start using it.
          </Text>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={onFinishConnecting}
              loading={isConnecting}
              disabled={isConnecting}
            >
              Finish connecting
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => dismiss.mutate(request.id)}
              disabled={dismiss.isPending}
            >
              Dismiss
            </Button>
          </div>
        </div>
      ))}
      {pending.map((request: GithubInstallRequestItem) => (
        <div
          key={request.id}
          className="flex flex-col gap-2 rounded-(--radius-2) border border-(--blue-6) bg-(--blue-2) px-3 py-2"
        >
          <Text size="sm">
            GitHub sent your request
            {request.github_login ? (
              <>
                {" "}
                (as <span className="font-medium">{request.github_login}</span>)
              </>
            ) : null}{" "}
            to your organization owners. Once an owner approves the PostHog app,
            we'll finish connecting here.
          </Text>
          {installUrl ? (
            <code className="whitespace-normal break-words rounded-(--radius-1) bg-(--gray-3) px-2 py-1 text-(--gray-11) text-xs">
              {buildOrgOwnerMessage(installUrl)}
            </code>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {installUrl ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => copy(buildOrgOwnerMessage(installUrl))}
              >
                {copied ? "Copied" : "Copy message for your org owner"}
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => dismiss.mutate(request.id)}
              disabled={dismiss.isPending}
            >
              Dismiss
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  GitBranchIcon,
} from "@phosphor-icons/react";
import {
  describeGithubConnectError,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
} from "@posthog/core/integrations/connectErrors";
import {
  describeGithubRepoAccess,
  formatGithubAccountLabel,
} from "@posthog/core/settings/githubRepoSummary";
import { Button, Spinner, Text } from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { GithubInstallRequestsBanner } from "@posthog/ui/features/integrations/components/GithubInstallRequestsBanner";
import { RequestIntegrationAccessForm } from "@posthog/ui/features/integrations/components/RequestIntegrationAccessForm";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import { useGithubConnect } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";

interface GitHubIntegrationSectionProps {
  hasGithubIntegration: boolean;
  isLoading?: boolean;
  /** When false, omit the dashed bottom rule (e.g. inside a parent `divide-y` list). */
  showBottomBorder?: boolean;
}

/**
 * The compact "is this project connected to GitHub" row used by Self-driving setup. Full
 * management (disconnect, personal installations) lives on the GitHub settings page.
 */
export function GitHubIntegrationSection({
  hasGithubIntegration,
  isLoading = false,
  showBottomBorder = true,
}: GitHubIntegrationSectionProps) {
  const borderClass = showBottomBorder
    ? "border-border border-b border-dashed pb-4"
    : "";
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { isAdmin } = useIsOrgAdmin();
  const { githubIntegrations } = useIntegrationSelectors();
  const { repositories, getIntegrationIdForRepo, isLoadingRepos } =
    useRepositoryIntegration();
  const {
    error: connectError,
    isConnecting: connecting,
    isTimedOut: timedOut,
    hasError: hasConnectError,
    isPending: awaitingApproval,
    connect: handleConnect,
  } = useGithubConnect({
    projectId,
    projectHasTeamIntegration: hasGithubIntegration,
  });

  if (isLoading) {
    return (
      <div className={`flex items-center justify-between gap-4 ${borderClass}`}>
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="size-[20px] shrink-0 animate-pulse rounded bg-gray-4" />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="h-[12px] w-[40%] animate-pulse rounded bg-gray-4" />
            <div className="h-[11px] w-[60%] animate-pulse rounded bg-gray-3" />
          </div>
        </div>
        <div className="h-[24px] w-[120px] shrink-0 animate-pulse rounded bg-gray-3" />
      </div>
    );
  }

  const summaries = githubIntegrations.map((integration) => {
    const installationId = String(integration.config?.installation_id ?? "");
    const accountLabel = formatGithubAccountLabel(
      integration.config?.account,
      installationId,
    );
    const repos = repositories.filter(
      (repo) => getIntegrationIdForRepo(repo) === integration.id,
    );
    const selection = integration.config?.repository_selection ?? null;
    return {
      id: integration.id,
      accountLabel,
      repos,
      summary: describeGithubRepoAccess({
        selection,
        total: selection === "all" && !isLoadingRepos ? repos.length : null,
        repos,
        accountLabel,
      }),
      unavailable: integration.installation_status === "unavailable",
    };
  });

  // A row GitHub has removed still counts toward hasGithubIntegration, but it can't grant code
  // access — so the connected tick needs a genuinely available installation, not just any row.
  const hasConnectedIntegration = summaries.some((entry) => !entry.unavailable);

  const statusLine = hasGithubIntegration ? (
    <div className="flex flex-col gap-0.5">
      {summaries.map((entry) => (
        <Tooltip
          key={entry.id}
          content={
            entry.repos.length > 0 ? (
              <div className="flex max-h-64 flex-col gap-0.5 overflow-y-auto">
                {entry.repos.map((repo) => (
                  <Text key={repo} size="xs">
                    {repo}
                  </Text>
                ))}
              </div>
            ) : (
              entry.summary.label
            )
          }
          side="bottom"
        >
          <span className="flex cursor-help items-center gap-1">
            <Text
              size="xs"
              className={
                entry.unavailable ? "text-(--red-11)" : "text-(--gray-11)"
              }
            >
              {entry.unavailable
                ? `Removed from ${entry.accountLabel} on GitHub`
                : `${entry.accountLabel}: ${isLoadingRepos ? "loading repositories…" : entry.summary.label}`}
            </Text>
          </span>
        </Tooltip>
      ))}
    </div>
  ) : (
    <Text
      size="xs"
      className={hasConnectError ? "text-(--red-11)" : "text-(--gray-11)"}
    >
      {hasConnectError
        ? describeGithubConnectError(connectError)
        : timedOut
          ? GITHUB_CONNECT_TIMEOUT_MESSAGE
          : "Required for Self-driving to work"}
    </Text>
  );

  const showAdminHandoff =
    !hasGithubIntegration && !awaitingApproval && isAdmin === false;

  return (
    <div className={`flex flex-col gap-3 ${borderClass}`}>
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="shrink-0 text-(--gray-11)">
            <GitBranchIcon size={20} />
          </div>
          <div className="flex min-w-0 flex-col">
            <Text size="sm" weight="medium">
              Project-level code access
            </Text>
            {statusLine}
          </div>
        </div>
        {connecting ? (
          <Spinner />
        ) : (
          <div className="flex shrink-0 items-center gap-2">
            {hasConnectedIntegration ? (
              <CheckCircleIcon
                size={16}
                weight="fill"
                className="text-(--green-9)"
              />
            ) : null}
            {hasGithubIntegration ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => openSettings("github")}
              >
                Manage
              </Button>
            ) : showAdminHandoff || awaitingApproval ? null : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isAdmin === null}
                onClick={() => void handleConnect()}
              >
                {hasConnectError || timedOut ? "Try again" : "Connect GitHub"}
                <ArrowSquareOutIcon size={12} />
              </Button>
            )}
          </div>
        )}
      </div>
      {projectId != null ? (
        <GithubInstallRequestsBanner
          onFinishConnecting={() => void handleConnect()}
          isConnecting={connecting}
        />
      ) : null}
      {showAdminHandoff && projectId != null ? (
        <RequestIntegrationAccessForm
          projectId={projectId}
          kind="github"
          integrationName="GitHub"
        />
      ) : null}
    </div>
  );
}

import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import {
  describeIntegrationDisconnectError,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
  isAlreadyDisconnectedError,
} from "@posthog/core/integrations/connectErrors";
import { buildGithubDisconnectDescription } from "@posthog/core/integrations/disconnectCopy";
import type { Integration } from "@posthog/core/integrations/selectors";
import {
  describeGithubRepoAccess,
  formatGithubAccountLabel,
  githubInstallationSettingsUrl,
} from "@posthog/core/settings/githubRepoSummary";
import { Button, Spinner, Text } from "@posthog/quill";
import { formatRelativeTimeLong } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useIsOrgAdmin } from "@posthog/ui/features/auth/useOrgRole";
import { DisconnectIntegrationDialog } from "@posthog/ui/features/integrations/components/DisconnectIntegrationDialog";
import { GithubInstallRequestsBanner } from "@posthog/ui/features/integrations/components/GithubInstallRequestsBanner";
import { GithubRepoSummary } from "@posthog/ui/features/integrations/components/GithubRepoSummary";
import { RequestIntegrationAccessForm } from "@posthog/ui/features/integrations/components/RequestIntegrationAccessForm";
import { useIntegrationSelectors } from "@posthog/ui/features/integrations/store";
import {
  describeGithubConnectError,
  invalidateGithubQueries,
  useGithubConnect,
} from "@posthog/ui/features/integrations/useGithubUserConnect";
import {
  useIntegrations,
  useRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { toast } from "@posthog/ui/primitives/toast";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const SETTINGS_REFETCH_INTERVAL_MS = 30_000;

/**
 * The project's GitHub App connection: what Self-driving and cloud tasks run against. Mirrors
 * the web project settings so both surfaces describe the same installation the same way.
 */
export function ProjectGithubConnectionSection() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const { isLoading } = useIntegrations({
    refetchInterval: SETTINGS_REFETCH_INTERVAL_MS,
  });
  const { githubIntegrations, hasGithubIntegration } =
    useIntegrationSelectors();
  const { isAdmin } = useIsOrgAdmin();
  const {
    error: connectError,
    isConnecting,
    isTimedOut,
    hasError: hasConnectError,
    isPending: isAwaitingApproval,
    connect,
  } = useGithubConnect({
    projectId,
    projectHasTeamIntegration: hasGithubIntegration,
  });

  return (
    <SettingsSection
      label="Project connection"
      description="GitHub access for this project's Self-driving pipeline and cloud tasks"
    >
      {projectId != null ? (
        <GithubInstallRequestsBanner
          onFinishConnecting={() => void connect()}
          isConnecting={isConnecting}
        />
      ) : null}

      {hasConnectError ? (
        <Text size="xs" className="text-(--red-11)">
          {describeGithubConnectError(connectError)}
        </Text>
      ) : isTimedOut ? (
        <Text size="xs" variant="muted">
          {GITHUB_CONNECT_TIMEOUT_MESSAGE}
        </Text>
      ) : null}

      <SettingsCard>
        {isLoading ? (
          <div className="flex items-center gap-2 px-3.5 py-3">
            <Spinner />
            <Text size="xs" variant="muted">
              Loading…
            </Text>
          </div>
        ) : hasGithubIntegration ? (
          githubIntegrations.map((integration) => (
            <ProjectGithubIntegrationRow
              key={integration.id}
              integration={integration}
              projectId={projectId}
              canDisconnect={isAdmin === true}
            />
          ))
        ) : isAwaitingApproval ? (
          <SettingsCardRow
            label="No GitHub connection yet"
            description="A GitHub organization owner still needs to approve the PostHog app"
          />
        ) : isAdmin === false && projectId != null ? (
          <div className="px-3.5 py-3">
            <RequestIntegrationAccessForm
              projectId={projectId}
              kind="github"
              integrationName="GitHub"
            />
          </div>
        ) : (
          <SettingsCardRow
            label="No GitHub connection yet"
            description="Connect GitHub so Self-driving and cloud tasks can work with your repositories"
          >
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={projectId == null || isAdmin === null || isConnecting}
              onClick={() => void connect()}
            >
              {isConnecting ? <Spinner /> : <ArrowSquareOutIcon size={12} />}
              {isConnecting
                ? "Waiting for GitHub…"
                : hasConnectError || isTimedOut
                  ? "Try again"
                  : "Connect GitHub"}
            </Button>
          </SettingsCardRow>
        )}
      </SettingsCard>
    </SettingsSection>
  );
}

interface ProjectGithubIntegrationRowProps {
  integration: Integration;
  projectId: number | null;
  canDisconnect: boolean;
}

function ProjectGithubIntegrationRow({
  integration,
  projectId,
  canDisconnect,
}: ProjectGithubIntegrationRowProps) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const {
    repositories,
    getIntegrationIdForRepo,
    isLoadingRepos,
    failedIntegrationIds,
  } = useRepositoryIntegration();

  const hasRepoFetchFailed = failedIntegrationIds.includes(integration.id);

  const installationId =
    integration.config?.installation_id ?? integration.integration_id ?? "";
  const accountLabel = formatGithubAccountLabel(
    integration.config?.account,
    String(installationId),
  );
  const repos = repositories.filter(
    (repo) => getIntegrationIdForRepo(repo) === integration.id,
  );
  const selection = integration.config?.repository_selection ?? null;
  const summary = describeGithubRepoAccess({
    selection,
    total: selection === "all" && !isLoadingRepos ? repos.length : null,
    repos,
    accountLabel,
  });
  const status =
    integration.installation_status === "unavailable"
      ? "unavailable"
      : "connected";
  const settingsUrl = installationId
    ? githubInstallationSettingsUrl({
        installation_id: String(installationId),
        account: integration.config?.account,
      })
    : null;

  const disconnect = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      if (projectId == null) throw new Error("No project selected");
      await client.deleteIntegration(projectId, integration.id);
    },
    onSuccess: () => {
      setConfirmOpen(false);
      toast.success("GitHub disconnected from this project.");
      invalidateGithubQueries(queryClient, projectId);
    },
    onError: (error) => {
      if (isAlreadyDisconnectedError(error)) {
        setConfirmOpen(false);
        toast.info("Already disconnected.");
        invalidateGithubQueries(queryClient, projectId);
        return;
      }
      toast.error(
        describeIntegrationDisconnectError(
          error,
          "Failed to disconnect GitHub.",
        ),
      );
    },
  });

  return (
    <>
      <GithubRepoSummary
        accountLabel={accountLabel}
        summary={summary}
        repos={repos}
        status={status}
        isLoadingRepos={isLoadingRepos}
        hasRepoFetchFailed={hasRepoFetchFailed}
        meta={
          typeof integration.created_at === "string"
            ? `Connected ${formatRelativeTimeLong(integration.created_at)}`
            : undefined
        }
        onManage={
          settingsUrl ? () => void openUrlInBrowser(settingsUrl) : undefined
        }
        actions={
          canDisconnect ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-(--red-11)"
              disabled={disconnect.isPending}
              onClick={() => setConfirmOpen(true)}
            >
              {status === "unavailable" ? "Remove" : "Disconnect"}
            </Button>
          ) : null
        }
      />
      <DisconnectIntegrationDialog
        open={confirmOpen}
        title={
          status === "unavailable"
            ? `Remove ${accountLabel} from this project?`
            : `Disconnect GitHub from ${accountLabel}?`
        }
        description={
          status === "unavailable"
            ? "The PostHog app is no longer installed on GitHub, so this only removes the stale connection from PostHog"
            : buildGithubDisconnectDescription(
                accountLabel,
                integration.installation_shared === true,
                "project",
              )
        }
        confirmLabel={status === "unavailable" ? "Remove" : "Disconnect"}
        isPending={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}

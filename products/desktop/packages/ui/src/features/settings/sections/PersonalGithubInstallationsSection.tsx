import { ArrowSquareOutIcon, GithubLogoIcon } from "@phosphor-icons/react";
import type { UserGitHubIntegration } from "@posthog/api-client/posthog-client";
import { isAlreadyDisconnectedError } from "@posthog/core/integrations/connectErrors";
import { buildGithubDisconnectDescription } from "@posthog/core/integrations/disconnectCopy";
import {
  describeGithubRepoAccess,
  formatGithubAccountLabel,
  githubInstallationSettingsUrl,
} from "@posthog/core/settings/githubRepoSummary";
import { Button, Spinner, Text } from "@posthog/quill";
import { formatRelativeTimeLong } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { DisconnectIntegrationDialog } from "@posthog/ui/features/integrations/components/DisconnectIntegrationDialog";
import { GithubRepoSummary } from "@posthog/ui/features/integrations/components/GithubRepoSummary";
import {
  describeGithubConnectError,
  invalidateGithubQueries,
  useGithubUserConnect,
} from "@posthog/ui/features/integrations/useGithubUserConnect";
import {
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import {
  SettingsCard,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { toast } from "@posthog/ui/primitives/toast";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const SETTINGS_REFETCH_INTERVAL_MS = 30_000;

/**
 * The user's own GitHub App installations. Agents use these to act as the user (commits,
 * pull requests, review comments), independent of which project is open.
 */
export function PersonalGithubInstallationsSection() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { data: integrations = [], isLoading } = useUserGithubIntegrations({
    refetchInterval: SETTINGS_REFETCH_INTERVAL_MS,
  });
  const { reposByInstallationId, failedInstallationIds, isLoadingRepos } =
    useUserRepositoryIntegration();
  const {
    error,
    isConnecting,
    hasError: hasConnectError,
    connect,
    reset,
  } = useGithubUserConnect({ projectId });
  const canConnect = projectId != null && cloudRegion != null && !isConnecting;

  const handleConnect = () => {
    if (hasConnectError) reset();
    void connect();
  };

  return (
    <SettingsSection
      label="Your GitHub account"
      description="Personal GitHub installations linked to your PostHog account. Agents use these to act as you."
      action={
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canConnect}
          onClick={handleConnect}
        >
          {isConnecting ? <Spinner /> : <ArrowSquareOutIcon size={12} />}
          {isConnecting
            ? "Waiting…"
            : integrations.length === 0
              ? "Connect GitHub"
              : "Connect another account"}
        </Button>
      }
    >
      {hasConnectError ? (
        <Text size="xs" className="text-(--red-11)">
          {describeGithubConnectError(error)}
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
        ) : integrations.length === 0 ? (
          <div className="flex items-center gap-3 px-3.5 py-3">
            <div className="shrink-0 text-(--gray-11)">
              <GithubLogoIcon size={20} />
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="font-medium text-[13px] text-gray-12 leading-5">
                No GitHub account linked yet
              </span>
              <span className="text-[12px] text-gray-10 leading-snug">
                Connect one so agents can open pull requests as you.
              </span>
            </div>
          </div>
        ) : (
          integrations.map((integration) => (
            <PersonalGithubInstallationRow
              key={integration.installation_id}
              integration={integration}
              repos={reposByInstallationId[integration.installation_id] ?? []}
              hasRepoFetchFailed={failedInstallationIds.includes(
                integration.installation_id,
              )}
              isLoadingRepos={isLoadingRepos}
              projectId={projectId}
            />
          ))
        )}
      </SettingsCard>
    </SettingsSection>
  );
}

interface PersonalGithubInstallationRowProps {
  integration: UserGitHubIntegration;
  repos: string[];
  hasRepoFetchFailed: boolean;
  isLoadingRepos: boolean;
  projectId: number | null;
}

function PersonalGithubInstallationRow({
  integration,
  repos,
  hasRepoFetchFailed,
  isLoadingRepos,
  projectId,
}: PersonalGithubInstallationRowProps) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const accountLabel = formatGithubAccountLabel(
    integration.account,
    integration.installation_id,
  );
  const selection = integration.repository_selection ?? null;
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
  const settingsUrl = githubInstallationSettingsUrl(integration);

  const disconnect = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      await client.disconnectGithubUserIntegration(integration.installation_id);
    },
    onSuccess: () => {
      setConfirmOpen(false);
      toast.success("Disconnected GitHub account");
      invalidateGithubQueries(queryClient, projectId);
    },
    onError: (err) => {
      if (isAlreadyDisconnectedError(err)) {
        setConfirmOpen(false);
        toast.info("Already disconnected.");
        invalidateGithubQueries(queryClient, projectId);
        return;
      }
      toast.error(
        err instanceof Error ? err.message : "Failed to disconnect GitHub",
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
          integration.created_at
            ? `Connected ${formatRelativeTimeLong(integration.created_at)}`
            : "Connected"
        }
        onManage={() => void openUrlInBrowser(settingsUrl)}
        actions={
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
        }
      />
      <DisconnectIntegrationDialog
        open={confirmOpen}
        title={
          status === "unavailable"
            ? `Remove ${accountLabel}?`
            : `Disconnect ${accountLabel}?`
        }
        description={
          status === "unavailable"
            ? "The PostHog app is no longer installed on GitHub, so this only removes the stale link from your account."
            : buildGithubDisconnectDescription(
                accountLabel,
                integration.installation_shared === true,
                "account",
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

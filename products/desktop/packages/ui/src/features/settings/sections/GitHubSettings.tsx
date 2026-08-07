import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  CaretRightIcon,
  GearSixIcon,
  GitBranchIcon,
  GithubLogoIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { UserGitHubIntegration } from "@posthog/api-client/posthog-client";
import { githubInstallationSettingsUrl } from "@posthog/core/settings/githubRepoSummary";
import { formatRelativeTimeLong } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  describeGithubConnectError,
  invalidateGithubQueries,
  useGithubUserConnect,
} from "@posthog/ui/features/integrations/useGithubUserConnect";
import {
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { toast } from "@posthog/ui/primitives/toast";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import {
  AlertDialog,
  Box,
  Button,
  Flex,
  IconButton,
  Spinner,
  Text,
  Tooltip,
} from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

const REPO_PREVIEW_COUNT = 3;

export function GitHubSettings() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const { data: integrations = [], isLoading } = useUserGithubIntegrations();
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

  const connectButtonLabel =
    integrations.length === 0 ? "Connect GitHub" : "Connect another account";

  return (
    <Flex direction="column" gap="3">
      <Flex align="center" justify="between" gap="3" wrap="wrap">
        <Text className="text-(--gray-11) text-[13px]">
          Personal GitHub installations linked to your PostHog account.
        </Text>
        <Button
          size="1"
          disabled={!canConnect}
          onClick={handleConnect}
          className="shrink-0"
        >
          {isConnecting ? (
            <Spinner size="1" />
          ) : (
            <ArrowSquareOutIcon size={12} />
          )}
          {isConnecting ? "Waiting…" : connectButtonLabel}
        </Button>
      </Flex>

      {hasConnectError && (
        <Text className="text-(--red-11) text-[13px]">
          {describeGithubConnectError(error)}
        </Text>
      )}

      <Flex direction="column" className="border-(--gray-5) border-t">
        {isLoading ? (
          <Flex align="center" gap="2" py="4">
            <Spinner size="1" />
            <Text className="text-(--gray-11) text-[13px]">Loading…</Text>
          </Flex>
        ) : integrations.length === 0 ? (
          <Flex align="center" gap="3" py="4">
            <Box className="shrink-0 text-(--gray-11)">
              <GithubLogoIcon size={20} />
            </Box>
            <Text className="text-(--gray-11) text-[13px]">
              No GitHub integrations yet. Connect one to enable cloud tasks.
            </Text>
          </Flex>
        ) : (
          integrations.map((integration) => (
            <GitHubIntegrationRow
              key={integration.installation_id}
              integration={integration}
              repos={reposByInstallationId[integration.installation_id] ?? []}
              hasRepoFetchFailed={failedInstallationIds.includes(
                integration.installation_id,
              )}
              isLoadingRepos={isLoadingRepos}
            />
          ))
        )}
      </Flex>
    </Flex>
  );
}

interface GitHubIntegrationRowProps {
  integration: UserGitHubIntegration;
  repos: string[];
  hasRepoFetchFailed: boolean;
  isLoadingRepos: boolean;
}

function GitHubIntegrationRow({
  integration,
  repos,
  hasRepoFetchFailed,
  isLoadingRepos,
}: GitHubIntegrationRowProps) {
  const apiClient = useOptionalAuthenticatedClient();
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const disconnect = useMutation({
    mutationFn: async () => {
      if (!apiClient) throw new Error("Not authenticated");
      await apiClient.disconnectGithubUserIntegration(
        integration.installation_id,
      );
    },
    onSuccess: () => {
      setConfirmOpen(false);
      toast.success("Disconnected GitHub account");
      invalidateGithubQueries(queryClient, projectId);
    },
    onError: (err) => {
      toast.error(
        err instanceof Error ? err.message : "Failed to disconnect GitHub",
      );
    },
  });

  const rawAccountName = integration.account?.name;
  const accountName =
    (typeof rawAccountName === "string" && rawAccountName.trim()) ||
    "GitHub account";
  const repoCount = repos.length;
  const canExpand = repoCount > 0;
  const settingsUrl = githubInstallationSettingsUrl(integration);

  const repoPreview = repos.slice(0, REPO_PREVIEW_COUNT).join(", ");
  const repoRemainder = repoCount - REPO_PREVIEW_COUNT;

  const repoSummaryNode = isLoadingRepos ? (
    <Text className="text-(--gray-11) text-[13px]">Loading repositories…</Text>
  ) : hasRepoFetchFailed ? (
    <Flex align="center" gap="1">
      <WarningIcon
        size={13}
        weight="fill"
        className="shrink-0 text-(--amber-9)"
      />
      <Text className="text-(--amber-11) text-[13px]">
        Couldn't load repositories
      </Text>
    </Flex>
  ) : repoCount === 0 ? (
    <Text className="text-(--gray-11) text-[13px]">
      No repositories accessible
    </Text>
  ) : (
    <Text className="text-(--gray-11) text-[13px]" truncate>
      {repoCount} {repoCount === 1 ? "repository" : "repositories"} accessible:{" "}
      <Text className="text-(--gray-12)">{repoPreview}</Text>
      {repoRemainder > 0 ? ` and ${repoRemainder} more` : ""}
    </Text>
  );

  return (
    <>
      <Flex
        direction="column"
        gap="2"
        py="3"
        className="border-(--gray-5) border-b"
      >
        <Flex align="start" justify="between" gap="4">
          <Flex align="start" gap="3" className="min-w-0 flex-1">
            <Box className="shrink-0 text-(--gray-11)">
              <GithubLogoIcon size={28} />
            </Box>
            <Flex direction="column" gap="1" className="min-w-0">
              <Text className="text-(--gray-12) text-sm">
                <Text className="font-medium">Connected</Text> to{" "}
                <button
                  type="button"
                  onClick={() => void openUrlInBrowser(settingsUrl)}
                  className="cursor-pointer font-medium underline hover:text-(--accent-11)"
                >
                  {accountName}
                </button>
              </Text>
              {integration.created_at && (
                <Text className="text-(--gray-11) text-[13px]">
                  Created {formatRelativeTimeLong(integration.created_at)}
                </Text>
              )}
              <Flex align="center" gap="2" className="min-w-0">
                <Flex align="center" gap="1" className="min-w-0 flex-1">
                  <GitBranchIcon
                    size={13}
                    className="shrink-0 text-(--gray-10)"
                  />
                  {canExpand ? (
                    <button
                      type="button"
                      onClick={() => setExpanded((v) => !v)}
                      className="-mx-1 flex min-w-0 cursor-pointer items-center gap-1 rounded px-1 text-left transition-colors hover:bg-(--gray-3)"
                    >
                      {expanded ? (
                        <CaretDownIcon
                          size={11}
                          className="shrink-0 text-(--gray-10)"
                        />
                      ) : (
                        <CaretRightIcon
                          size={11}
                          className="shrink-0 text-(--gray-10)"
                        />
                      )}
                      {repoSummaryNode}
                    </button>
                  ) : (
                    repoSummaryNode
                  )}
                </Flex>
                <Tooltip content="Manage on GitHub">
                  <IconButton
                    size="1"
                    variant="soft"
                    color="gray"
                    onClick={() => void openUrlInBrowser(settingsUrl)}
                    className="shrink-0"
                  >
                    <GearSixIcon size={12} />
                  </IconButton>
                </Tooltip>
              </Flex>
            </Flex>
          </Flex>
          <Button
            size="1"
            variant="soft"
            color="red"
            disabled={disconnect.isPending}
            onClick={() => setConfirmOpen(true)}
            className="shrink-0"
          >
            {disconnect.isPending ? <Spinner size="1" /> : null}
            Disconnect
          </Button>
        </Flex>
        {expanded && canExpand && (
          <div className="ml-9 max-h-48 overflow-y-auto rounded-(--radius-2) border border-(--gray-5) bg-(--gray-2)">
            <Flex direction="column" py="1">
              {repos.map((repo) => (
                <Text
                  key={repo}
                  className="px-2 py-0.5 text-(--gray-11) text-[13px]"
                  truncate
                >
                  {repo}
                </Text>
              ))}
            </Flex>
          </div>
        )}
      </Flex>

      <AlertDialog.Root
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!disconnect.isPending) setConfirmOpen(open);
        }}
      >
        <AlertDialog.Content maxWidth="420px" size="1">
          <AlertDialog.Title className="text-sm">
            Disconnect {accountName}?
          </AlertDialog.Title>
          <AlertDialog.Description>
            <Text color="gray" className="text-[13px]">
              You won't be able to create cloud tasks against repos in this
              installation until you reconnect.
            </Text>
          </AlertDialog.Description>
          <Flex justify="end" gap="3" mt="3">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" size="1">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <Button
              variant="solid"
              color="red"
              size="1"
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate()}
            >
              {disconnect.isPending ? <Spinner size="1" /> : null}
              Disconnect
            </Button>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </>
  );
}

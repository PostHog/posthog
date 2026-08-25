import {
  ArrowSquareOut,
  ArrowsClockwise,
  CheckCircle,
  GearSix,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import {
  GITHUB_CONNECT_PENDING_APPROVAL_CODE,
  isGithubConnectPendingApproval,
} from "@posthog/core/integrations/connectErrors";
import { githubInvalidationKeys } from "@posthog/core/integrations/connectMachine";
import {
  buildConnectAbandonedProps,
  buildConnectFailedProps,
  buildConnectFailureFingerprint,
  buildInstallationSettingsUrl,
  deriveAlternativeConnectedProjects,
  deriveConnectButtonState,
  deriveGithubApprovalState,
  getGithubPanelMessage,
  isAnyIntegrationStale,
  resolveSelectedProjectId,
} from "@posthog/core/onboarding/githubConnectPanel";
import type { GithubConnectService } from "@posthog/core/onboarding/githubConnectService";
import { GITHUB_CONNECT_SERVICE } from "@posthog/core/onboarding/identifiers";
import { formatGithubAccountLabel } from "@posthog/core/settings/githubRepoSummary";
import { useService } from "@posthog/di/react";
import { Button as QuillButton } from "@posthog/quill";
import type { OnboardingGithubConnectFlow } from "@posthog/shared/analytics-events";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { GithubApprovalNotice } from "@posthog/ui/features/integrations/GithubApprovalNotice";
import { useGithubDisconnect } from "@posthog/ui/features/integrations/useGithubDisconnect";
import { useGithubInstallRequests } from "@posthog/ui/features/integrations/useGithubInstallRequests";
import {
  describeGithubConnectError,
  useGithubConnect,
} from "@posthog/ui/features/integrations/useGithubUserConnect";
import {
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { useProjectsWithIntegrations } from "@posthog/ui/features/onboarding/hooks/useProjectsWithIntegrations";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import {
  AlertDialog,
  Button,
  Flex,
  IconButton,
  Skeleton,
  Spinner,
  Text,
} from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

export function GitHubConnectPanel() {
  const queryClient = useQueryClient();
  const currentProjectId = useAuthStateValue((state) => state.currentProjectId);
  const { projects, projectsWithGithub, isLoading } =
    useProjectsWithIntegrations();
  const manuallySelectedProjectId = useOnboardingStore(
    (state) => state.selectedProjectId,
  );
  const selectedProjectId = useMemo(
    () =>
      resolveSelectedProjectId(
        manuallySelectedProjectId,
        currentProjectId,
        projects,
      ),
    [manuallySelectedProjectId, currentProjectId, projects],
  );
  const selectedProject = useMemo(
    () => projects.find((p) => p.id === selectedProjectId),
    [projects, selectedProjectId],
  );

  // Armed on connect start, cleared on any terminal outcome, so an unmount in
  // between is reported as an abandoned connect.
  const inFlightConnectRef = useRef<{
    flowType: OnboardingGithubConnectFlow;
    startedAtMs: number;
  } | null>(null);

  const {
    error: connectError,
    isConnecting,
    isTimedOut: timedOut,
    hasError: hasConnectError,
    isPending: awaitingApproval,
    connect: handleConnectGitHub,
    reset: resetConnect,
  } = useGithubConnect({
    projectId: selectedProjectId,
    projectHasTeamIntegration: selectedProject?.hasGithubIntegration ?? null,
    onConnected: () => {
      inFlightConnectRef.current = null;
      track(ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECTED);
    },
  });
  const canTakeAction = !isConnecting && !timedOut && !hasConnectError;
  // The callback reports an org-owner wait through onPending when the caller
  // handles it, and on the error channel otherwise, so both are read here.
  const isPendingApproval =
    awaitingApproval || isGithubConnectPendingApproval(connectError?.code);

  // Every path that begins a connect, including reconnect, must go through
  // this, or its "started" event has no abandoned counterpart.
  const markConnectStarted = (
    flowType: OnboardingGithubConnectFlow,
    isRetry = false,
  ) => {
    track(ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECT_STARTED, {
      flow_type: flowType,
      is_retry: isRetry,
    });
    inFlightConnectRef.current = { flowType, startedAtMs: Date.now() };
  };

  const initiateConnect = (
    flowType: OnboardingGithubConnectFlow,
    isRetry = false,
  ) => {
    markConnectStarted(flowType, isRetry);
    void handleConnectGitHub();
  };

  useEffect(() => {
    return () => {
      const inFlight = inFlightConnectRef.current;
      if (!inFlight) return;
      track(
        ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECT_ABANDONED,
        buildConnectAbandonedProps({
          flowType: inFlight.flowType,
          startedAtMs: inFlight.startedAtMs,
          nowMs: Date.now(),
        }),
      );
    };
  }, []);

  const connectService = useService<GithubConnectService>(
    GITHUB_CONNECT_SERVICE,
  );
  useEffect(() => {
    const failureInputs = {
      hasConnectError,
      timedOut,
      errorCode: connectError?.code,
    };
    // A pending approval ends the flow without an error, so it carries no
    // failure fingerprint of its own; reuse the code so it stays deduped and
    // still counts as terminal for the abandonment marker below.
    const fingerprint = isPendingApproval
      ? GITHUB_CONNECT_PENDING_APPROVAL_CODE
      : buildConnectFailureFingerprint(failureInputs);
    const flowType = inFlightConnectRef.current?.flowType ?? "user_new";
    // Clear the marker only on a terminal outcome — even a deduped one. A
    // non-terminal re-run (a retry moving error/timeout back to connecting)
    // must leave it intact so a later unmount still records the abandonment.
    if (fingerprint !== null) {
      inFlightConnectRef.current = null;
    }
    if (!connectService.shouldReportFailure(fingerprint)) return;
    if (isPendingApproval) {
      track(ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECT_PENDING_ADMIN, {
        flow_type: flowType,
      });
      return;
    }
    track(
      ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECT_FAILED,
      buildConnectFailedProps(failureInputs),
    );
  }, [
    hasConnectError,
    timedOut,
    connectError,
    connectService,
    isPendingApproval,
  ]);

  const defaultPanelMessage = getGithubPanelMessage({
    hasConnectError,
    connectErrorMessage: describeGithubConnectError(connectError),
    timedOut,
    isConnecting,
    isPending: awaitingApproval,
  });

  const {
    data: githubUserIntegrations = [],
    isLoading: githubUserIntegrationsLoading,
  } = useUserGithubIntegrations();
  const hasGitIntegration = githubUserIntegrations.length > 0;
  const { data: githubInstallRequests } = useGithubInstallRequests();
  const approvalState = deriveGithubApprovalState({
    errorCode: connectError?.code,
    requests: githubInstallRequests?.results ?? [],
    hasIntegration: hasGitIntegration,
  });
  const isAwaitingApproval = approvalState === "awaiting";
  const isApprovedNotLinked = approvalState === "approved";
  const { failedInstallationIds, reposByInstallationId } =
    useUserRepositoryIntegration();
  const anyIntegrationStale = isAnyIntegrationStale(
    githubUserIntegrations,
    failedInstallationIds,
  );

  const alternativeConnectedProjects = useMemo(
    () =>
      deriveAlternativeConnectedProjects(
        hasGitIntegration,
        projectsWithGithub,
        selectedProjectId,
      ),
    [hasGitIntegration, projectsWithGithub, selectedProjectId],
  );
  const [selectedAlternativeId] = useState<number | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const refreshGithubState = async () => {
    setIsRefreshing(true);
    try {
      await Promise.all(
        githubInvalidationKeys(selectedProjectId).map((queryKey) =>
          queryClient.invalidateQueries({ queryKey: [...queryKey] }),
        ),
      );
    } finally {
      setIsRefreshing(false);
    }
  };
  const selectedAlternative = useMemo(() => {
    if (!alternativeConnectedProjects.length) return null;
    return (
      alternativeConnectedProjects.find(
        (p) => p.id === selectedAlternativeId,
      ) ?? alternativeConnectedProjects[0]
    );
  }, [alternativeConnectedProjects, selectedAlternativeId]);

  // Which connect path applies. The user presses the same button either way.
  const teamConnectFlow: OnboardingGithubConnectFlow | null =
    selectedProject?.hasGithubIntegration
      ? "team_existing"
      : selectedAlternative && selectedProject
        ? "team_alternative"
        : null;

  const [reconnectingInstallationId, setReconnectingInstallationId] = useState<
    string | null
  >(null);
  const [disconnectTarget, setDisconnectTarget] = useState<{
    installationId: string;
    accountName: string;
  } | null>(null);
  const { disconnect, isDisconnecting, reconnect } =
    useGithubDisconnect(selectedProjectId);

  return (
    <div>
      <Flex direction="column" gap="3">
        <Flex direction="column" gap="1" className="empty:hidden">
          {(isLoading || githubUserIntegrationsLoading) && (
            <Skeleton className="h-[16px] w-[80px]" />
          )}
          {!isLoading &&
            !githubUserIntegrationsLoading &&
            hasGitIntegration &&
            anyIntegrationStale && (
              <Text className="text-(--amber-11) text-[13px]">
                Reconnect needed
              </Text>
            )}
          {!hasGitIntegration &&
            !isLoading &&
            !githubUserIntegrationsLoading &&
            (isAwaitingApproval ? (
              <GithubApprovalNotice state="awaiting" className="pt-3" />
            ) : isApprovedNotLinked ? (
              <GithubApprovalNotice state="approved" className="pt-3" />
            ) : defaultPanelMessage ? (
              <Text
                className={
                  hasConnectError
                    ? "text-(--red-11) text-sm"
                    : "text-(--gray-11) text-sm"
                }
              >
                {defaultPanelMessage}
              </Text>
            ) : null)}
        </Flex>
        {hasGitIntegration ? (
          <Flex direction="column" gap="3">
            {githubUserIntegrations.map((integration) => {
              const installationId = integration.installation_id;
              const accountName = formatGithubAccountLabel(
                integration.account,
                installationId,
              );
              const installRepos = reposByInstallationId[installationId];
              const isLoadingInstallRepos = installRepos === undefined;
              const isStale = failedInstallationIds.includes(installationId);
              const isReconnecting =
                reconnectingInstallationId === installationId;
              return (
                <Flex
                  key={integration.id}
                  direction="column"
                  gap="2"
                  p="3"
                  className="rounded-[10px] border border-(--gray-a4) bg-(--color-panel-solid)"
                >
                  <Flex align="center" justify="between" gap="2" wrap="wrap">
                    <Flex align="center" gap="2">
                      {!isStale && (
                        <CheckCircle
                          size={15}
                          weight="fill"
                          className="shrink-0 text-(--green-9)"
                        />
                      )}
                      <Text className="font-bold text-(--gray-12) text-sm">
                        {accountName}
                      </Text>
                      <Text className="text-(--gray-10) text-[12px]">
                        {integration.account?.type === "Organization"
                          ? "org"
                          : "personal"}
                      </Text>
                    </Flex>
                    {isStale && (
                      <Text className="text-(--amber-11) text-[12px]">
                        Reconnect needed
                      </Text>
                    )}
                    <Flex align="center" gap="3">
                      {!isStale && (
                        <Text className="text-(--gray-10) text-[12px]">
                          {isLoadingInstallRepos
                            ? "Loading…"
                            : installRepos.length === 1
                              ? "1 repo"
                              : `${installRepos.length} repos`}
                        </Text>
                      )}
                      <Tooltip content="Manage on GitHub">
                        <IconButton
                          size="1"
                          variant="ghost"
                          color="gray"
                          aria-label={`Manage ${accountName} on GitHub`}
                          onClick={() =>
                            openExternalUrl(
                              buildInstallationSettingsUrl(
                                integration.account,
                                installationId,
                              ),
                            )
                          }
                        >
                          <GearSix size={14} />
                        </IconButton>
                      </Tooltip>
                      <Tooltip content="Disconnect">
                        <IconButton
                          size="1"
                          variant="ghost"
                          color="gray"
                          aria-label={`Disconnect ${accountName}`}
                          onClick={() =>
                            setDisconnectTarget({ installationId, accountName })
                          }
                        >
                          <Trash size={14} />
                        </IconButton>
                      </Tooltip>
                    </Flex>
                  </Flex>
                  <Flex
                    align="center"
                    gap="3"
                    wrap="wrap"
                    className="empty:hidden"
                  >
                    {isStale && (
                      <Button
                        size="1"
                        variant="solid"
                        loading={isReconnecting}
                        disabled={
                          reconnectingInstallationId !== null && !isReconnecting
                        }
                        onClick={async () => {
                          markConnectStarted("user_new", true);
                          setReconnectingInstallationId(installationId);
                          try {
                            await reconnect(
                              installationId,
                              handleConnectGitHub,
                            );
                          } catch {
                            // The pre-connect disconnect failed, so no
                            // connect flow ever started; a later unmount
                            // must not report this as user abandonment.
                            inFlightConnectRef.current = null;
                          } finally {
                            setReconnectingInstallationId(null);
                          }
                        }}
                      >
                        Reconnect
                        <ArrowSquareOut size={12} />
                      </Button>
                    )}
                  </Flex>
                </Flex>
              );
            })}
            <Flex align="center" gap="3" wrap="wrap">
              <Button
                size="1"
                variant="soft"
                color="gray"
                loading={isRefreshing}
                onClick={() => void refreshGithubState()}
              >
                <ArrowsClockwise size={12} />
                Refresh
              </Button>
              <Button
                size="1"
                variant="ghost"
                color="gray"
                onClick={() => initiateConnect("user_new")}
                loading={isConnecting}
              >
                <Plus size={12} />
                Add another GitHub org
              </Button>
            </Flex>
          </Flex>
        ) : isAwaitingApproval ? (
          <Button
            size="2"
            variant="soft"
            color="gray"
            className="self-start"
            loading={isRefreshing}
            onClick={() => void refreshGithubState()}
          >
            <ArrowsClockwise size={12} />
            Check again
          </Button>
        ) : isApprovedNotLinked ? (
          <QuillButton
            variant="primary"
            size="lg"
            className="h-[44px] w-full"
            loading={isConnecting}
            onClick={() => initiateConnect("user_new")}
          >
            Sign in with GitHub
            <ArrowSquareOut size={12} />
          </QuillButton>
        ) : !isLoading && !githubUserIntegrationsLoading ? (
          teamConnectFlow && canTakeAction ? (
            <Button
              size="3"
              variant="solid"
              onClick={() => initiateConnect(teamConnectFlow)}
              className="w-full"
            >
              Sign in with GitHub
              <ArrowSquareOut size={12} />
            </Button>
          ) : (
            <Flex direction="column" gap="2" className="w-full">
              <Button
                size="3"
                variant="solid"
                onClick={() => {
                  const { isRetry, shouldReset } = deriveConnectButtonState({
                    isConnecting,
                    hasConnectError,
                    timedOut,
                  });
                  if (shouldReset) resetConnect();
                  initiateConnect("user_new", isRetry);
                }}
                loading={isConnecting}
                className="w-full"
              >
                {
                  deriveConnectButtonState({
                    isConnecting,
                    hasConnectError,
                    timedOut,
                  }).label
                }
                <ArrowSquareOut size={12} />
              </Button>
              {hasConnectError && (
                <Button
                  size="1"
                  variant="ghost"
                  color="gray"
                  onClick={resetConnect}
                  className="self-start"
                >
                  Dismiss
                </Button>
              )}
            </Flex>
          )
        ) : null}
      </Flex>
      <AlertDialog.Root
        open={disconnectTarget !== null}
        onOpenChange={(next: boolean) => {
          if (!next && !isDisconnecting) {
            setDisconnectTarget(null);
          }
        }}
      >
        <AlertDialog.Content maxWidth="450px">
          <AlertDialog.Title>
            Disconnect{" "}
            {disconnectTarget ? disconnectTarget.accountName : "GitHub"}
          </AlertDialog.Title>
          <AlertDialog.Description className="text-sm">
            This removes your personal GitHub authorization from PostHog. You
            can reconnect at any time. The GitHub App itself stays installed in
            your org, so uninstall it on GitHub if you want to remove that too.
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" disabled={isDisconnecting}>
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <Button
              variant="solid"
              color="red"
              onClick={() => {
                if (!disconnectTarget) return;
                disconnect({ installationId: disconnectTarget.installationId });
                setDisconnectTarget(null);
              }}
              disabled={isDisconnecting}
            >
              {isDisconnecting ? <Spinner size="1" /> : null}
              Disconnect
            </Button>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}

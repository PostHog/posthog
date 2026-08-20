import {
  ArrowSquareOut,
  ArrowsClockwise,
  CheckCircle,
  GearSix,
  GithubLogo,
  Plus,
} from "@phosphor-icons/react";
import { isGithubConnectPendingApproval } from "@posthog/core/integrations/connectErrors";
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
import { useService } from "@posthog/di/react";
import { Button as QuillButton } from "@posthog/quill";
import type { OnboardingGithubConnectFlow } from "@posthog/shared/analytics-events";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { GithubApprovalNotice } from "@posthog/ui/features/integrations/GithubApprovalNotice";
import { useGithubDisconnect } from "@posthog/ui/features/integrations/useGithubDisconnect";
import {
  describeGithubConnectError,
  useGithubConnect,
} from "@posthog/ui/features/integrations/useGithubUserConnect";
import {
  useGithubInstallRequests,
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { OptionalBadge } from "@posthog/ui/features/onboarding/components/OptionalBadge";
import { PANEL_SHADOW } from "@posthog/ui/features/onboarding/components/onboardingStyles";
import { useProjectsWithIntegrations } from "@posthog/ui/features/onboarding/hooks/useProjectsWithIntegrations";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import {
  AlertDialog,
  Box,
  Button,
  DropdownMenu,
  Flex,
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
  const setSelectedProjectId = useOnboardingStore(
    (state) => state.selectProjectId,
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
  const isPendingApproval = isGithubConnectPendingApproval(connectError?.code);

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
    const fingerprint = buildConnectFailureFingerprint(failureInputs);
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
  });

  const {
    data: githubUserIntegrations = [],
    isLoading: githubUserIntegrationsLoading,
  } = useUserGithubIntegrations();
  const hasGitIntegration = githubUserIntegrations.length > 0;
  const { data: githubInstallRequests = [] } = useGithubInstallRequests();
  const approvalState = deriveGithubApprovalState({
    errorCode: connectError?.code,
    requests: githubInstallRequests,
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
  const [selectedAlternativeId, setSelectedAlternativeId] = useState<
    number | null
  >(null);
  const selectedAlternative = useMemo(() => {
    if (!alternativeConnectedProjects.length) return null;
    return (
      alternativeConnectedProjects.find(
        (p) => p.id === selectedAlternativeId,
      ) ?? alternativeConnectedProjects[0]
    );
  }, [alternativeConnectedProjects, selectedAlternativeId]);

  const [disconnectTarget, setDisconnectTarget] = useState<{
    installationId: string;
    accountName: string;
  } | null>(null);
  const [reconnectingInstallationId, setReconnectingInstallationId] = useState<
    string | null
  >(null);
  const { disconnect, isDisconnecting, reconnect } =
    useGithubDisconnect(selectedProjectId);

  return (
    <>
      <Box
        p="5"
        style={{ boxShadow: PANEL_SHADOW }}
        className="rounded-[12px] border border-(--gray-a3) bg-(--color-panel-solid)"
      >
        <Flex direction="column" gap="4">
          <Flex direction="column" gap="1">
            <Flex align="center" justify="between" gap="2">
              <Flex align="center" gap="2">
                <GithubLogo size={18} className="text-(--gray-12)" />
                <Text className="font-bold text-(--gray-12) text-base">
                  Connect GitHub
                </Text>
              </Flex>
              {isLoading || githubUserIntegrationsLoading ? (
                <Skeleton className="h-[16px] w-[80px]" />
              ) : hasGitIntegration ? (
                anyIntegrationStale ? (
                  <Text className="text-(--amber-11) text-[13px]">
                    Reconnect needed
                  </Text>
                ) : (
                  <Flex align="center" gap="1">
                    <CheckCircle
                      size={14}
                      weight="fill"
                      className="text-(--green-9)"
                    />
                    <Text className="text-(--green-11) text-[13px]">
                      {githubUserIntegrations.length > 1
                        ? `Connected (${githubUserIntegrations.length})`
                        : "Connected"}
                    </Text>
                  </Flex>
                )
              ) : (
                <OptionalBadge />
              )}
            </Flex>
            {!hasGitIntegration &&
              !isLoading &&
              !githubUserIntegrationsLoading &&
              (selectedProject?.hasGithubIntegration && canTakeAction ? (
                <Text className="text-(--gray-11) text-sm">
                  GitHub is already set up on{" "}
                  <Text className="font-bold">{selectedProject.name}</Text>.
                  Sign in with one click to link your account, no admin approval
                  needed.
                </Text>
              ) : selectedAlternative && selectedProject && canTakeAction ? (
                <Text className="text-(--gray-11) text-sm">
                  GitHub is already connected on{" "}
                  {alternativeConnectedProjects.length > 1 ? (
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger>
                        <button
                          type="button"
                          className="cursor-pointer border-0 bg-transparent p-0 font-bold text-(--gray-12) underline"
                        >
                          {selectedAlternative.name} +{" "}
                          {alternativeConnectedProjects.length - 1} more
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Content size="1" align="start">
                        {alternativeConnectedProjects.map((p) => (
                          <DropdownMenu.Item
                            key={p.id}
                            onSelect={() => setSelectedAlternativeId(p.id)}
                          >
                            <Text className="text-[13px]">{p.name}</Text>
                            <Text className="ml-2 text-(--gray-10) text-[13px]">
                              {p.organization.name}
                            </Text>
                          </DropdownMenu.Item>
                        ))}
                      </DropdownMenu.Content>
                    </DropdownMenu.Root>
                  ) : (
                    <>
                      <Text className="font-bold">
                        {selectedAlternative.name}
                      </Text>{" "}
                      ({selectedAlternative.organization.name})
                    </>
                  )}
                  .
                </Text>
              ) : isAwaitingApproval ? (
                <GithubApprovalNotice state="awaiting" className="pt-3" />
              ) : isApprovedNotLinked ? (
                <GithubApprovalNotice state="approved" className="pt-3" />
              ) : (
                <Text
                  className={
                    hasConnectError
                      ? "text-(--red-11) text-sm"
                      : "text-(--gray-11) text-sm"
                  }
                >
                  {defaultPanelMessage}
                </Text>
              ))}
          </Flex>
          {hasGitIntegration ? (
            <Flex direction="column" gap="3">
              {githubUserIntegrations.map((integration) => {
                const installationId = integration.installation_id;
                const accountName = integration.account?.name ?? "GitHub";
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
                    className="rounded-[8px] border border-(--gray-a3)"
                  >
                    <Flex align="center" justify="between" gap="2" wrap="wrap">
                      <Flex align="center" gap="2">
                        <Text className="font-bold text-(--gray-12) text-sm">
                          {accountName}
                        </Text>
                        <Text className="text-(--gray-10) text-[12px]">
                          {integration.account?.type === "Organization"
                            ? "org"
                            : "personal"}
                        </Text>
                      </Flex>
                      {isStale ? (
                        <Text className="text-(--amber-11) text-[12px]">
                          Reconnect needed
                        </Text>
                      ) : (
                        <Text className="text-(--gray-10) text-[12px]">
                          {isLoadingInstallRepos
                            ? "Loading…"
                            : installRepos.length === 1
                              ? "1 repo"
                              : `${installRepos.length} repos`}
                        </Text>
                      )}
                    </Flex>
                    <Flex align="center" gap="3" wrap="wrap">
                      {isStale && (
                        <Button
                          size="1"
                          variant="solid"
                          loading={isReconnecting}
                          disabled={
                            reconnectingInstallationId !== null &&
                            !isReconnecting
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
                      <Button
                        size="1"
                        variant="soft"
                        color="gray"
                        onClick={() => {
                          openExternalUrl(
                            buildInstallationSettingsUrl(
                              integration.account,
                              installationId,
                            ),
                          );
                        }}
                      >
                        <GearSix size={12} />
                        Settings
                      </Button>
                      <Button
                        size="1"
                        variant="soft"
                        color="red"
                        onClick={() =>
                          setDisconnectTarget({ installationId, accountName })
                        }
                      >
                        Disconnect
                      </Button>
                    </Flex>
                  </Flex>
                );
              })}
              <Flex align="center" gap="3" wrap="wrap">
                <Button
                  size="1"
                  variant="soft"
                  color="gray"
                  onClick={() => {
                    queryClient.invalidateQueries({
                      queryKey: ["integrations"],
                    });
                    queryClient.invalidateQueries({
                      queryKey: ["user-github-integrations"],
                    });
                  }}
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
          ) : isAwaitingApproval ? null : isApprovedNotLinked ? (
            <QuillButton
              variant="primary"
              size="sm"
              className="self-start"
              loading={isConnecting}
              onClick={() => initiateConnect("user_new")}
            >
              Connect GitHub
              <ArrowSquareOut size={12} />
            </QuillButton>
          ) : !isLoading && !githubUserIntegrationsLoading ? (
            selectedProject?.hasGithubIntegration && canTakeAction ? (
              <Button
                size="2"
                variant="solid"
                onClick={() => initiateConnect("team_existing")}
                className="self-start"
              >
                Sign in with GitHub
                <ArrowSquareOut size={12} />
              </Button>
            ) : selectedAlternative && selectedProject && canTakeAction ? (
              <Flex direction="column" gap="2" align="start">
                <Button
                  size="2"
                  variant="solid"
                  onClick={() => initiateConnect("team_alternative")}
                >
                  Connect GitHub on {selectedProject.name}
                  <ArrowSquareOut size={12} />
                </Button>
                <Button
                  size="1"
                  variant="ghost"
                  color="gray"
                  onClick={() => setSelectedProjectId(selectedAlternative.id)}
                >
                  Switch to {selectedAlternative.name}
                </Button>
              </Flex>
            ) : (
              <Flex gap="2" align="center">
                <Button
                  size="2"
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
                    size="2"
                    variant="ghost"
                    color="gray"
                    onClick={resetConnect}
                  >
                    Dismiss
                  </Button>
                )}
              </Flex>
            )
          ) : null}
        </Flex>
      </Box>

      <AlertDialog.Root
        open={disconnectTarget !== null}
        onOpenChange={(next) => {
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
            your org — uninstall it on GitHub if you want to remove that too.
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
    </>
  );
}

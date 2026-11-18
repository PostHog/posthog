import {
  ArrowSquareOut,
  ArrowsClockwise,
  CheckCircle,
  GearSix,
  Info,
  Plus,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  GITHUB_CONNECT_PENDING_APPROVAL_CODE,
  isGithubConnectAlreadyLinked,
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
  didGithubConnectCompleteFromIntegrations,
  getGithubPanelMessage,
  isAnyIntegrationStale,
  resolveSelectedProjectId,
} from "@posthog/core/onboarding/githubConnectPanel";
import type { GithubConnectService } from "@posthog/core/onboarding/githubConnectService";
import { GITHUB_CONNECT_SERVICE } from "@posthog/core/onboarding/identifiers";
import { formatGithubAccountLabel } from "@posthog/core/settings/githubRepoSummary";
import { useService } from "@posthog/di/react";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
  Skeleton,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { OnboardingGithubConnectFlow } from "@posthog/shared/analytics-events";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { DisconnectIntegrationDialog } from "@posthog/ui/features/integrations/components/DisconnectIntegrationDialog";
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
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  const {
    data: githubUserIntegrations = [],
    isLoading: githubUserIntegrationsLoading,
  } = useUserGithubIntegrations();

  // Armed on connect start, cleared on any terminal outcome, so an unmount in
  // between is reported as an abandoned connect.
  const inFlightConnectRef = useRef<{
    flowType: OnboardingGithubConnectFlow;
    startedAtMs: number;
    integrationCountAtStart: number;
  } | null>(null);

  const reportConnected = useCallback(() => {
    if (!inFlightConnectRef.current) return;
    inFlightConnectRef.current = null;
    track(ANALYTICS_EVENTS.ONBOARDING_GITHUB_CONNECTED);
  }, []);

  const {
    error: connectError,
    isConnecting,
    isTimedOut: timedOut,
    hasError: hasConnectError,
    isPending: awaitingApproval,
    connect: handleConnectGitHub,
    connectUser: handleConnectAdditionalGitHub,
    reset: resetConnect,
  } = useGithubConnect({
    projectId: selectedProjectId,
    projectHasTeamIntegration: selectedProject?.hasGithubIntegration ?? null,
    onConnected: reportConnected,
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
    inFlightConnectRef.current = {
      flowType,
      startedAtMs: Date.now(),
      integrationCountAtStart: githubUserIntegrations.length,
    };
  };

  const initiateConnect = (
    flowType: OnboardingGithubConnectFlow,
    isRetry = false,
  ) => {
    markConnectStarted(flowType, isRetry);
    void handleConnectGitHub();
  };

  const initiateAdditionalConnect = () => {
    markConnectStarted("user_new");
    void handleConnectAdditionalGitHub();
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

  useEffect(() => {
    const inFlight = inFlightConnectRef.current;
    if (!inFlight) return;
    // The integration query can confirm success before Electron receives the
    // deep-link callback. A new integration is a second success signal.
    if (
      !didGithubConnectCompleteFromIntegrations({
        isConnecting,
        integrationCountAtStart: inFlight.integrationCountAtStart,
        currentIntegrationCount: githubUserIntegrations.length,
      })
    ) {
      return;
    }
    resetConnect();
    reportConnected();
  }, [
    githubUserIntegrations.length,
    isConnecting,
    reportConnected,
    resetConnect,
  ]);

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
  const isAlreadyLinked = isGithubConnectAlreadyLinked(connectError);

  const hasGitIntegration = githubUserIntegrations.length > 0;
  const { data: githubInstallRequests } = useGithubInstallRequests();
  const approvalState = deriveGithubApprovalState({
    errorCode: connectError?.code,
    requests: githubInstallRequests?.results ?? [],
    hasIntegration: hasGitIntegration,
  });
  const isAwaitingApproval = approvalState === "awaiting";
  const isApprovedNotLinked = approvalState === "approved";
  const {
    failedInstallationIds,
    reposByInstallationId,
    isRefreshingRepos,
    refreshRepositories,
  } = useUserRepositoryIntegration();
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
  const [isCheckingStatus, setIsCheckingStatus] = useState(false);
  const checkGithubState = async () => {
    setIsCheckingStatus(true);
    try {
      await Promise.all(
        githubInvalidationKeys(selectedProjectId).map((queryKey) =>
          queryClient.invalidateQueries({ queryKey: [...queryKey] }),
        ),
      );
    } finally {
      setIsCheckingStatus(false);
    }
  };
  const selectedAlternative = alternativeConnectedProjects[0] ?? null;

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
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1 empty:hidden">
          {!isLoading &&
            !githubUserIntegrationsLoading &&
            hasGitIntegration &&
            anyIntegrationStale && (
              <Text size="xs" className="text-warning-foreground">
                Reconnect needed
              </Text>
            )}
          {!hasGitIntegration &&
            !isLoading &&
            !githubUserIntegrationsLoading &&
            (isAwaitingApproval ? (
              <GithubApprovalNotice state="awaiting" />
            ) : isApprovedNotLinked ? (
              <GithubApprovalNotice state="approved" />
            ) : defaultPanelMessage ? (
              <Text
                size="sm"
                variant={hasConnectError ? "destructive" : "muted"}
              >
                {defaultPanelMessage}
              </Text>
            ) : null)}
        </div>
        {hasGitIntegration ? (
          <div className="flex flex-col gap-3">
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
                <Item
                  key={integration.id}
                  variant="outline"
                  size="sm"
                  tone={isStale ? "warning" : "success"}
                  className="w-full pr-2"
                >
                  <ItemMedia variant="icon">
                    {isStale ? (
                      <WarningCircle
                        size={15}
                        weight="fill"
                        className="text-warning-foreground"
                      />
                    ) : (
                      <CheckCircle
                        size={15}
                        weight="fill"
                        className="text-success-foreground"
                      />
                    )}
                  </ItemMedia>
                  <ItemContent>
                    <ItemTitle className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-semibold">
                        {accountName}
                      </span>
                      <Badge variant="default">
                        {integration.account?.type === "Organization"
                          ? "org"
                          : "personal"}
                      </Badge>
                    </ItemTitle>
                    {isStale && (
                      <ItemDescription className="text-warning-foreground">
                        Reconnect needed
                      </ItemDescription>
                    )}
                  </ItemContent>
                  <ItemActions className="flex shrink-0 items-center gap-2">
                    {!isStale && (
                      <Text size="xs" variant="muted">
                        {isLoadingInstallRepos
                          ? "Loading..."
                          : installRepos.length === 1
                            ? "1 repo"
                            : `${installRepos.length} repos`}
                      </Text>
                    )}
                    {isStale && (
                      <Button
                        size="sm"
                        variant="outline"
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
                              handleConnectAdditionalGitHub,
                            );
                          } catch {
                            // The pre-connect disconnect failed, so no
                            // connect flow ever started. A later unmount
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
                    <DropdownMenu>
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <DropdownMenuTrigger
                              render={
                                <Button
                                  size="icon-sm"
                                  variant="default"
                                  aria-label={`Manage ${accountName}`}
                                >
                                  <GearSix size={14} />
                                </Button>
                              }
                            />
                          }
                        />
                        <TooltipContent>Manage</TooltipContent>
                      </Tooltip>
                      <DropdownMenuContent
                        align="end"
                        side="bottom"
                        sideOffset={6}
                        className="min-w-fit"
                      >
                        <DropdownMenuItem
                          onClick={() =>
                            openExternalUrl(
                              buildInstallationSettingsUrl(
                                integration.account,
                                installationId,
                              ),
                            )
                          }
                        >
                          Open settings on GitHub
                          <ArrowSquareOut size={12} className="ml-auto" />
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() =>
                            setDisconnectTarget({
                              installationId,
                              accountName,
                            })
                          }
                        >
                          Disconnect...
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </ItemActions>
                </Item>
              );
            })}
            <div className="flex flex-wrap items-center gap-2">
              {isRefreshingRepos ? (
                <Skeleton className="h-6 w-[76px] rounded-md" />
              ) : (
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => void refreshRepositories()}
                >
                  <ArrowsClockwise size={12} />
                  Refresh
                </Button>
              )}
              {isConnecting ? (
                <Skeleton className="h-6 w-[171px] rounded-md" />
              ) : (
                <Button
                  size="sm"
                  variant="link-muted"
                  onClick={initiateAdditionalConnect}
                >
                  <Plus size={12} />
                  Add org
                </Button>
              )}
            </div>
            {defaultPanelMessage && (
              <Item
                variant="muted"
                size="sm"
                tone={
                  isAlreadyLinked
                    ? "info"
                    : hasConnectError
                      ? "destructive"
                      : "warning"
                }
              >
                <ItemMedia variant="icon">
                  {isAlreadyLinked ? (
                    <Info size={15} weight="fill" />
                  ) : (
                    <WarningCircle size={15} weight="fill" />
                  )}
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>
                    {isAlreadyLinked
                      ? "No other GitHub organizations to add"
                      : hasConnectError
                        ? "Couldn't connect GitHub"
                        : timedOut
                          ? "GitHub did not respond"
                          : "Waiting for approval"}
                  </ItemTitle>
                  <ItemDescription>{defaultPanelMessage}</ItemDescription>
                </ItemContent>
              </Item>
            )}
          </div>
        ) : isAwaitingApproval ? (
          <Button
            size="sm"
            variant="outline"
            className="self-start"
            loading={isCheckingStatus}
            onClick={() => void checkGithubState()}
          >
            <ArrowsClockwise size={12} />
            Check again
          </Button>
        ) : isApprovedNotLinked ? (
          <Button
            variant="primary"
            size="lg"
            className="w-full"
            loading={isConnecting}
            onClick={() => initiateConnect("user_new")}
          >
            Sign in with GitHub
            <ArrowSquareOut size={12} />
          </Button>
        ) : !isLoading && !githubUserIntegrationsLoading ? (
          teamConnectFlow && canTakeAction ? (
            <Button
              size="lg"
              variant="primary"
              onClick={() => initiateConnect(teamConnectFlow)}
              className="w-fit self-center"
            >
              Sign in with GitHub
              <ArrowSquareOut size={12} />
            </Button>
          ) : (
            <div className="flex w-full flex-col gap-2">
              <Button
                size="lg"
                variant="primary"
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
                className="w-fit self-center"
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
                  size="sm"
                  variant="link-muted"
                  onClick={resetConnect}
                  className="self-start"
                >
                  Dismiss
                </Button>
              )}
            </div>
          )
        ) : null}
      </div>
      <DisconnectIntegrationDialog
        open={disconnectTarget !== null}
        title={`Disconnect ${disconnectTarget?.accountName ?? "GitHub"}`}
        description="This removes your personal GitHub authorization from PostHog. The GitHub app stays installed. Remove it in GitHub if you also want to uninstall the app."
        isPending={isDisconnecting}
        onCancel={() => setDisconnectTarget(null)}
        onConfirm={() => {
          if (!disconnectTarget) return;
          disconnect({ installationId: disconnectTarget.installationId });
          setDisconnectTarget(null);
        }}
      />
    </div>
  );
}

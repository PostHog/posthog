import {
  ArrowLeftIcon,
  CheckCircleIcon,
  LinkIcon,
  PauseIcon,
  PencilSimpleIcon,
  PlayIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { isUploadableSkillSource } from "@posthog/core/message-editor/skillTags";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Badge,
  Button,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { assertCloudUsageAvailable } from "@posthog/ui/features/billing/preflightCloudUsage";
import { useUsageLimitStore } from "@posthog/ui/features/billing/usageLimitStore";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Button as ActionButton } from "@posthog/ui/primitives/Button";
import { TimezoneTimestamp } from "@posthog/ui/primitives/TimezoneTimestamp";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import { toast } from "@posthog/ui/primitives/toast";
import {
  canGoBackInHistory,
  goBackInHistory,
  navigateToLoops,
} from "@posthog/ui/router/navigationBridge";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { Flex, Text } from "@radix-ui/themes";
import type { ParsedHistoryState } from "@tanstack/history";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLoop } from "../hooks/useLoop";
import {
  useDeleteLoop,
  useRunLoop,
  useUpdateLoop,
} from "../hooks/useLoopMutations";
import { RECENT_RUNS_LIMIT, useLoopRuns } from "../hooks/useLoopRuns";
import { useSyncLoopSkillBundles } from "../hooks/useLoopSkillBundles";
import {
  buildLoopEnabledToggledProps,
  buildLoopViewedProps,
} from "../loopAnalytics";
import {
  describeTrigger,
  loopFireBlockedMessage,
  loopPausedDescription,
  loopStatusColor,
  loopStatusLabel,
  nextScheduleRun,
  summarizeNotificationDestinations,
} from "../loopDisplay";
import { formatLoopModel } from "../loopModels";
import { loopSkillBundles, primaryLoopSkillBundle } from "../loopSkill";
import { copyLoopLink } from "../utils/copyLoopLink";
import { LoopLoadError } from "./LoopFallbacks";
import { LoopForm } from "./LoopForm";
import { LoopHeaderTitle } from "./LoopHeaderTitle";
import { LoopRunRow } from "./LoopRunRow";
import { LoopSpaceBreadcrumb } from "./LoopSpaceBreadcrumb";

type PendingNavigation = {
  action: "PUSH" | "REPLACE" | "BACK" | "FORWARD" | "GO";
  delta: number | null;
  href: string;
  state: ParsedHistoryState;
};

export function LoopDetailView({
  loopId,
  startEditing = false,
}: {
  loopId: string;
  startEditing?: boolean;
}) {
  const hasLoopListOrigin = useLocation({
    select: (location) => location.state.loopListOrigin === true,
  });
  const { data: loop, isLoading, isError } = useLoop(loopId);
  const updateLoop = useUpdateLoop(loopId);
  const deleteLoop = useDeleteLoop();
  const runLoop = useRunLoop(loopId);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [pendingLeaveAction, setPendingLeaveAction] = useState<
    "back" | "summary" | "navigation" | null
  >(null);
  const pendingNavigationRef = useRef<PendingNavigation | null>(null);
  const [runNowPending, setRunNowPending] = useState(false);
  const [isEditing, setIsEditing] = useState(startEditing);
  const [editDirty, setEditDirty] = useState(false);

  const runsQuery = useLoopRuns(loopId);
  const runs = runsQuery.data ?? [];

  const viewTrackedFor = useRef<string | null>(null);
  useEffect(() => {
    if (isLoading || runsQuery.isLoading || runsQuery.isError || !loop) return;
    if (viewTrackedFor.current === loop.id) return;
    viewTrackedFor.current = loop.id;
    track(
      ANALYTICS_EVENTS.LOOP_VIEWED,
      buildLoopViewedProps(loop, runs.length),
    );
  }, [isLoading, runsQuery.isLoading, runsQuery.isError, loop, runs.length]);

  // A loop attached to a space gets a breadcrumb back to it; one that belongs
  // to the project (or any loop while the spaces layout is off) still names
  // itself, it just has no parent to offer.
  const spacesLayout = useChannelsLayout();
  const contextTarget = loop?.context_target ?? null;
  const loopName = loop?.name ?? "Loop";
  useSetHeaderContent(
    useMemo(
      () =>
        spacesLayout && contextTarget ? (
          <LoopSpaceBreadcrumb
            folderId={contextTarget.folder_id}
            spaceName={contextTarget.name}
            leafLabel={loopName}
          />
        ) : (
          <LoopHeaderTitle label={loopName} />
        ),
      [spacesLayout, contextTarget, loopName],
    ),
  );

  const handleToggleEnabled = (enabled: boolean) => {
    if (!loop) return;
    updateLoop.mutate(
      { enabled },
      {
        onSuccess: () => {
          track(
            ANALYTICS_EVENTS.LOOP_ENABLED_TOGGLED,
            buildLoopEnabledToggledProps(loop, enabled, true),
          );
        },
        onError: (error) => {
          track(
            ANALYTICS_EVENTS.LOOP_ENABLED_TOGGLED,
            buildLoopEnabledToggledProps(loop, enabled, false),
          );
          toast.error("Failed to update loop", {
            description: error.message,
          });
        },
      },
    );
  };

  const handleRunNow = async () => {
    if (runNowPending || !loop) return;
    setRunNowPending(true);
    try {
      if (!(await assertCloudUsageAvailable())) return;
      const result = await runLoop.mutateAsync();
      if (result.created) {
        toast.success("Loop run started");
        track(ANALYTICS_EVENTS.LOOP_RUN_STARTED, {
          loop_id: loop.id,
          task_id: result.task_id,
          task_run_id: result.task_run_id,
          runtime_adapter: loop.runtime_adapter,
          model: loop.model || undefined,
          trigger_count: loop.triggers.length,
        });
      } else if (result.reason === "gate_blocked") {
        useUsageLimitStore.getState().show({ cause: "org_limit" });
        track(ANALYTICS_EVENTS.LOOP_RUN_BLOCKED, {
          loop_id: loop.id,
          reason: result.reason,
          overlap_policy: loop.overlap_policy,
          trigger_count: loop.triggers.length,
        });
      } else {
        toast.error("Run not started", {
          description: loopFireBlockedMessage(result.reason),
        });
        if (result.reason !== "created") {
          track(ANALYTICS_EVENTS.LOOP_RUN_BLOCKED, {
            loop_id: loop.id,
            reason: result.reason,
            overlap_policy: loop.overlap_policy,
            trigger_count: loop.triggers.length,
          });
        }
      }
    } catch (error) {
      toast.error("Failed to start run", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setRunNowPending(false);
    }
  };

  const handleDelete = () => {
    if (!loop) return;
    deleteLoop.mutate(loopId, {
      onSuccess: () => {
        track(ANALYTICS_EVENTS.LOOP_DELETED, {
          loop_id: loop.id,
          visibility: loop.visibility,
          enabled: loop.enabled,
          trigger_count: loop.triggers.length,
          consecutive_failures: loop.consecutive_failures,
        });
        toast.success("Loop deleted");
        navigateToLoops();
      },
      onError: (error) =>
        toast.error("Failed to delete loop", { description: error.message }),
    });
  };

  useEffect(() => {
    if (startEditing) setIsEditing(true);
  }, [startEditing]);

  const leavePage = useCallback(() => {
    if (hasLoopListOrigin && canGoBackInHistory()) {
      goBackInHistory();
      return;
    }
    navigateToLoops();
  }, [hasLoopListOrigin]);

  const requestLeaveEdit = (action: "back" | "summary") => {
    if (isEditing && editDirty) {
      setPendingLeaveAction(action);
      setDiscardOpen(true);
      return;
    }
    if (action === "back") {
      leavePage();
    } else {
      setIsEditing(false);
      setEditDirty(false);
    }
  };

  const continueBlockedNavigation = () => {
    const pendingNavigation = pendingNavigationRef.current;
    pendingNavigationRef.current = null;
    if (!pendingNavigation) return;

    const router = getRouterOrNull();
    if (!router) return;

    if (
      pendingNavigation.action === "BACK" ||
      pendingNavigation.action === "FORWARD" ||
      pendingNavigation.action === "GO"
    ) {
      if (pendingNavigation.delta !== null && pendingNavigation.delta !== 0) {
        router.history.go(pendingNavigation.delta, { ignoreBlocker: true });
      } else {
        router.history.push(pendingNavigation.href, pendingNavigation.state, {
          ignoreBlocker: true,
        });
      }
      return;
    }

    if (pendingNavigation.action === "REPLACE") {
      router.history.replace(pendingNavigation.href, pendingNavigation.state, {
        ignoreBlocker: true,
      });
      return;
    }

    router.history.push(pendingNavigation.href, pendingNavigation.state, {
      ignoreBlocker: true,
    });
  };

  const discardChanges = () => {
    const action = pendingLeaveAction;
    setDiscardOpen(false);
    setPendingLeaveAction(null);
    setEditDirty(false);
    setIsEditing(false);
    if (action === "back") {
      if (hasLoopListOrigin && canGoBackInHistory()) {
        getRouterOrNull()?.history.back({ ignoreBlocker: true });
        return;
      }
      navigateToLoops({ ignoreBlocker: true });
    } else if (action === "navigation") {
      continueBlockedNavigation();
    }
  };

  useEffect(() => {
    if (!isEditing || !editDirty) return;
    const router = getRouterOrNull();
    if (!router) return;

    return router.history.block({
      enableBeforeUnload: true,
      blockerFn: ({ currentLocation, nextLocation, action }) => {
        if (nextLocation.href === currentLocation.href) return false;

        const delta =
          typeof nextLocation.state.__TSR_index === "number" &&
          typeof currentLocation.state.__TSR_index === "number"
            ? nextLocation.state.__TSR_index - currentLocation.state.__TSR_index
            : null;
        pendingNavigationRef.current = {
          action,
          delta,
          href: nextLocation.href,
          state: nextLocation.state,
        };
        setPendingLeaveAction("navigation");
        setDiscardOpen(true);
        return true;
      },
    });
  }, [isEditing, editDirty]);

  useEffect(() => {
    if (!isEditing || !editDirty) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isEditing, editDirty]);

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-5xl px-8 py-8">
        <div className="h-24 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
      </div>
    );
  }

  if (isError || !loop) {
    return <LoopLoadError />;
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <Flex
        direction="column"
        gap="5"
        className="mx-auto w-full max-w-5xl px-8 py-8"
      >
        <Flex direction="column" gap="3">
          <Button
            variant="link-muted"
            size="sm"
            onClick={() => requestLeaveEdit("back")}
            className="w-fit px-0"
          >
            <ArrowLeftIcon size={15} />
            Back
          </Button>

          <Flex align="center" justify="between" gap="3" wrap="wrap">
            <Flex align="center" gap="2" wrap="wrap" className="min-w-0">
              <Text
                className="truncate font-bold text-[22px] text-gray-12 leading-tight tracking-tight"
                title={loop.name}
              >
                {loop.name}
              </Text>
              <Badge variant={loopStatusBadgeVariant(loop)}>
                {loopStatusLabel(loop)}
              </Badge>
              <Badge>{formatVisibility(loop.visibility)}</Badge>
            </Flex>
            <Flex align="center" gap="2">
              <Button
                variant="outline"
                size="sm"
                loading={updateLoop.isPending}
                disabled={updateLoop.isPending}
                onClick={() => handleToggleEnabled(!loop.enabled)}
              >
                {loop.enabled ? (
                  <PauseIcon size={14} />
                ) : (
                  <PlayIcon size={14} />
                )}
                {loop.enabled ? "Pause" : "Resume"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => copyLoopLink(loop)}
              >
                <LinkIcon size={14} />
                Copy link
              </Button>
              <Button
                variant="outline"
                size="sm"
                loading={runNowPending}
                disabled={runNowPending}
                onClick={() => void handleRunNow()}
              >
                <PlayIcon size={14} />
                Run now
              </Button>
              <Button
                variant="outline"
                size="sm"
                className={
                  isEditing
                    ? "border-(--accent-7) bg-(--accent-3) text-(--accent-11)"
                    : undefined
                }
                onClick={() => {
                  if (isEditing) {
                    requestLeaveEdit("summary");
                    return;
                  }
                  setIsEditing(true);
                }}
              >
                {isEditing ? (
                  <CheckCircleIcon size={14} weight="fill" />
                ) : (
                  <PencilSimpleIcon size={14} />
                )}
                {isEditing ? "Editing" : "Edit"}
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setDeleteOpen(true)}
              >
                <TrashIcon size={14} />
                Delete
              </Button>
            </Flex>
          </Flex>

          <Text
            className={`max-w-3xl text-[12.5px] leading-snug ${
              loop.description.trim() ? "text-gray-11" : "text-gray-10"
            }`}
          >
            {loop.description.trim() || "No description"}
          </Text>

          <PausedNotice loop={loop} />
        </Flex>

        {isEditing ? (
          <LoopForm
            loop={loop}
            variant="embedded"
            onDirtyChange={setEditDirty}
            onCancel={() => requestLeaveEdit("summary")}
            onSaved={() => {
              setIsEditing(false);
              setEditDirty(false);
              toast.success("Loop updated");
            }}
          />
        ) : (
          <>
            <ConfigSummarySection loop={loop} />
            <InstructionsSection loop={loop} />
          </>
        )}

        <Flex direction="column" gap="2">
          <Flex align="center" gap="2">
            <Text className="font-medium text-[13px] text-gray-12">
              Run history
            </Text>
            <Text className="text-[11px] text-gray-10">
              {RECENT_RUNS_LIMIT} most recent
            </Text>
          </Flex>
          {runsQuery.isLoading ? (
            <div className="h-16 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
          ) : runs.length === 0 ? (
            <Flex
              direction="column"
              align="center"
              gap="1"
              className="rounded-(--radius-2) border border-(--gray-5) border-dashed px-6 py-8 text-center"
            >
              <Text className="font-medium text-[12.5px] text-gray-12">
                No runs yet
              </Text>
              <Text className="max-w-sm text-[11.5px] text-gray-10 leading-snug">
                Runs show up here once this loop fires. Trigger one with Run
                now, or wait for its next trigger.
              </Text>
            </Flex>
          ) : (
            <Flex direction="column" gap="2">
              {runs.map((run) => (
                <LoopRunRow
                  key={run.id}
                  loopId={loop.id}
                  run={run}
                  onStopped={() => void runsQuery.refetch()}
                />
              ))}
            </Flex>
          )}
        </Flex>
      </Flex>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete loop</AlertDialogTitle>
            <AlertDialogDescription>
              <Text color="gray" className="text-[13px]">
                Permanently delete{" "}
                <Text className="font-medium text-[13px]">{loop.name}</Text>?
                This stops every trigger and cannot be undone.
              </Text>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button
              variant="destructive"
              size="sm"
              loading={deleteLoop.isPending}
              disabled={deleteLoop.isPending}
              onClick={handleDelete}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={discardOpen} onOpenChange={setDiscardOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              <Text color="gray" className="text-[13px]">
                This loop has edits that haven't been saved. Leaving edit mode
                will discard them.
              </Text>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Keep editing
                </Button>
              }
            />
            <Button variant="destructive" size="sm" onClick={discardChanges}>
              Discard changes
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function loopStatusBadgeVariant(
  loop: LoopSchemas.Loop,
): "default" | "destructive" | "success" {
  const color = loopStatusColor(loop);
  if (color === "green") return "success";
  if (color === "red") return "destructive";
  return "default";
}

function formatVisibility(visibility: LoopSchemas.LoopVisibilityEnum): string {
  return visibility.charAt(0).toUpperCase() + visibility.slice(1);
}

function PausedNotice({ loop }: { loop: LoopSchemas.Loop }) {
  const description = loopPausedDescription(loop);
  if (!description) return null;

  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      wrap="wrap"
      className="rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-3 py-2"
    >
      <Text className="text-(--red-11) text-[12.5px] leading-snug">
        {description}
      </Text>
      {loop.disabled_reason === "usage_limited" ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            useUsageLimitStore.getState().show({ cause: "org_limit" })
          }
        >
          Manage plan
        </Button>
      ) : null}
    </Flex>
  );
}

function ConfigSummarySection({ loop }: { loop: LoopSchemas.Loop }) {
  const displayModel = formatLoopModel(loop.runtime_adapter, loop.model);
  const {
    members,
    isLoading: membersLoading,
    isError: membersError,
    isComplete: membersComplete,
  } = useOrgMembers({ enabled: loop.visibility === "team" });
  const creator = members.find((member) => member.id === loop.created_by_id);
  let creatorContent: React.ReactNode = null;
  if (loop.visibility === "team" && membersError) {
    creatorContent = "Creator unavailable";
  } else if (loop.visibility === "team" && membersLoading) {
    creatorContent = "Loading…";
  } else if (loop.visibility === "team" && creator) {
    creatorContent = (
      <Flex align="center" gap="2">
        <UserAvatar user={creator} size="xs" />
        {userDisplayName(creator)}
      </Flex>
    );
  } else if (loop.visibility === "team" && membersComplete) {
    creatorContent = "Former organization member";
  } else if (loop.visibility === "team") {
    creatorContent = "Creator unavailable";
  }
  const notificationDestinations = summarizeNotificationDestinations(
    loop.notifications,
  );

  return (
    <Flex direction="column" gap="3">
      <Text className="font-medium text-[13px] text-gray-12">
        Configuration
      </Text>

      <Flex
        direction="column"
        gap="3"
        className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) p-3"
      >
        <SummaryRow label="Model">
          {[
            loop.runtime_adapter,
            displayModel,
            loop.reasoning_effort ? `${loop.reasoning_effort} reasoning` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </SummaryRow>

        {loopSkillBundles(loop).length > 0 ? (
          <SummaryRow label="Skill">
            <LoopSkillSummary loop={loop} />
          </SummaryRow>
        ) : null}

        <SummaryRow label="Repository">
          {loop.repositories.length > 0
            ? loop.repositories.map((repo) => repo.full_name).join(", ")
            : "None (connector-only loop)"}
        </SummaryRow>

        {loop.visibility === "team" ? (
          <SummaryRow label="Created by">{creatorContent}</SummaryRow>
        ) : null}

        <SummaryRow label="Triggers">
          {loop.triggers.length === 0 ? (
            "No triggers configured"
          ) : (
            <Flex direction="column" gap="1">
              {loop.triggers.map((trigger) => (
                <Text key={trigger.id} className="text-[12.5px] text-gray-12">
                  <TriggerDescription trigger={trigger} />
                  {!trigger.enabled ? " (disabled)" : ""}
                </Text>
              ))}
            </Flex>
          )}
        </SummaryRow>

        {notificationDestinations.length > 0 ? (
          <SummaryRow label="Notifications">
            {notificationDestinations.join(", ")}
          </SummaryRow>
        ) : null}
      </Flex>
    </Flex>
  );
}

function LoopSkillSummary({ loop }: { loop: LoopSchemas.Loop }) {
  const { localWorkspaces } = useHostCapabilities();
  const trpc = useHostTRPC();
  const { data: localSkillData } = useQuery({
    ...trpc.skills.list.queryOptions(),
    enabled: localWorkspaces,
  });
  const syncSkillBundles = useSyncLoopSkillBundles();

  const primary = primaryLoopSkillBundle(loop);
  if (!primary) return null;
  const dependencyCount = loopSkillBundles(loop).length - 1;

  // The one-click refresh must be unambiguous about which skill it snapshots: it
  // requires exactly one local skill matching the stored name AND source, so a
  // same-named skill from another source (say, an opened repo) can never silently
  // replace the loop's snapshot. Ambiguous cases go through the edit form, where
  // the picker shows each candidate.
  const candidates = (localSkillData ?? []).filter(
    (skill) =>
      skill.name === primary.skill_name &&
      skill.source === primary.skill_source,
  );
  const localMatch = candidates.length === 1 ? candidates[0] : undefined;
  const updateDisabledReason = !localWorkspaces
    ? "updating the snapshot needs the desktop app"
    : localMatch
      ? null
      : candidates.length > 1
        ? `several local skills are named ${primary.skill_name}; pick the right one from the edit form`
        : `no local ${primary.skill_source} skill named ${primary.skill_name} was found on this machine`;

  const handleUpdate = () => {
    if (!localMatch || !isUploadableSkillSource(localMatch.source)) return;
    syncSkillBundles.mutate(
      {
        loopId: loop.id,
        skill: {
          name: localMatch.name,
          source: localMatch.source,
          path: localMatch.path,
        },
      },
      {
        onSuccess: () => toast.success("Skill snapshot updated"),
        onError: (error) =>
          toast.error("Failed to update the skill snapshot", {
            description: error.message,
          }),
      },
    );
  };

  return (
    <Flex align="center" gap="2" wrap="wrap">
      <Text className="text-[12.5px] text-gray-12">
        {primary.skill_name}
        {dependencyCount > 0
          ? ` (+${dependencyCount} ${dependencyCount === 1 ? "dependency" : "dependencies"})`
          : ""}
      </Text>
      <Text
        className="text-[11px] text-gray-10"
        title={new Date(primary.uploaded_at).toLocaleString()}
      >
        Snapshot {primary.content_sha256.slice(0, 8)}
      </Text>
      <ActionButton
        variant="soft"
        color="gray"
        size="1"
        loading={syncSkillBundles.isPending}
        disabled={syncSkillBundles.isPending || !!updateDisabledReason}
        disabledReason={updateDisabledReason}
        onClick={handleUpdate}
      >
        Update from local skill
      </ActionButton>
    </Flex>
  );
}

function InstructionsSection({ loop }: { loop: LoopSchemas.Loop }) {
  const primarySkill = primaryLoopSkillBundle(loop);

  return (
    <Flex direction="column" gap="3">
      <Text className="font-medium text-[13px] text-gray-12">Instructions</Text>
      <pre className="max-h-[400px] min-h-[160px] overflow-auto whitespace-pre-wrap rounded-(--radius-2) border border-border bg-(--color-panel-solid) p-3 font-sans text-[12.5px] text-gray-12 leading-relaxed">
        {loop.instructions}
      </pre>
      {primarySkill ? (
        <Text className="text-[11px] text-gray-10 leading-snug">
          This loop runs the {primarySkill.skill_name} skill: the leading /
          {primarySkill.skill_name} line invokes its attached snapshot.
        </Text>
      ) : null}
    </Flex>
  );
}

function TriggerDescription({ trigger }: { trigger: LoopSchemas.LoopTrigger }) {
  const description = describeTrigger(trigger);
  if (trigger.type !== "schedule") return description;

  const config = trigger.config as LoopSchemas.LoopScheduleTriggerConfig;
  const nextRun = nextScheduleRun(config);
  if (!nextRun) return description;
  const nextRunSeparator = " · Next run ";
  const [scheduleDescription, nextRunDescription] =
    description.split(nextRunSeparator);
  const timezone =
    config.timezone ?? (config.run_at ? systemTimezone() : "UTC");

  return (
    <>
      {scheduleDescription}
      {nextRunSeparator}
      <TimezoneTimestamp
        timestamp={nextRun}
        timezone={timezone}
        label={nextRunDescription}
      />
    </>
  );
}

function SummaryRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Flex direction="column" gap="1">
      <Text className="text-[11px] text-gray-10 uppercase tracking-wide">
        {label}
      </Text>
      <div className="text-[12.5px] text-gray-12">{children}</div>
    </Flex>
  );
}

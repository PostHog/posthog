import { ChatCircleDotsIcon } from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { Text } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Button } from "@posthog/ui/primitives/Button";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToTaskDetail } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef, useState } from "react";
import { useLoopBuilderSessions } from "../hooks/useLoopBuilderSessions";
import { useLoopLimitReason, useLoopLimits, useLoops } from "../hooks/useLoops";
import {
  type LoopBuilderSession,
  useLoopBuilderSessionStore,
} from "../loopBuilderSessionStore";
import { countLoops } from "../loopListFilters";
import type { LoopSpace } from "../loopScopes";
import type { LoopTemplate } from "../loopTemplates";
import { startNewLoop } from "../loopWizardDialogStore";
import { LoopBuilderComposer } from "./LoopBuilderComposer";
import { LoopsEmptyState } from "./LoopsEmptyState";
import { LoopsListSection } from "./LoopsListSection";
import { LoopsPageLayout } from "./LoopsPageLayout";
import { LoopTemplatesSection } from "./LoopTemplatesSection";
import { NewLoopButton } from "./NewLoopButton";

const EMPTY_SPACES: LoopSpace[] = [];

export function LoopsListView() {
  const { data: loops, isLoading, isError, error } = useLoops();
  const limits = useLoopLimits();
  const limitReason = useLoopLimitReason();
  const workflowBacked = useLoopsHogFlowsEnabled();

  useSetHeaderContent(null);

  const { sessions: builderSessions, isSettled: builderSessionsSettled } =
    useLoopBuilderSessions();

  const { channels: spaces } = useChannels();

  const allLoops = loops ?? [];
  const counts = countLoops(allLoops);

  const hasTrackedListViewedRef = useRef(false);
  useEffect(() => {
    if (
      isLoading ||
      isError ||
      !builderSessionsSettled ||
      hasTrackedListViewedRef.current
    )
      return;
    hasTrackedListViewedRef.current = true;
    track(ANALYTICS_EVENTS.LOOP_LIST_VIEWED, {
      loop_count: counts.total,
      personal_loop_count: counts.personal,
      team_loop_count: counts.team,
      global_loop_count: counts.global,
      space_count: counts.spaces,
      is_at_limit: limits?.atLimit ?? false,
      loop_limit: limits?.max,
      builder_session_count: builderSessions.length,
    });
  }, [
    isLoading,
    isError,
    builderSessionsSettled,
    counts.total,
    counts.personal,
    counts.team,
    counts.global,
    counts.spaces,
    limits,
    builderSessions.length,
  ]);

  return (
    <LoopsListViewPresentation
      loops={allLoops}
      spaces={spaces}
      isLoading={isLoading}
      error={isError ? error : null}
      limitReason={limitReason}
      showVisibilityFilter={!workflowBacked}
      builderSessions={builderSessions}
      onStartBlank={() => startNewLoop()}
      onStartFromTemplate={(template) => startNewLoop({ template })}
      onResumeBuilderSession={navigateToTaskDetail}
      onBuilderSessionStopped={(taskId) =>
        useLoopBuilderSessionStore.getState().removeSession(taskId)
      }
    />
  );
}

interface LoopsListViewPresentationProps {
  loops: LoopSchemas.Loop[];
  spaces?: LoopSpace[];
  isLoading?: boolean;
  error?: unknown;
  limitReason?: string | null;
  showVisibilityFilter?: boolean;
  builderSessions?: LoopBuilderSession[];
  onStartBlank: () => void;
  onStartFromTemplate: (template: LoopTemplate) => void;
  onResumeBuilderSession?: (taskId: string) => void;
  onBuilderSessionStopped?: (taskId: string) => void;
}

export function LoopsListViewPresentation({
  loops,
  spaces = EMPTY_SPACES,
  isLoading = false,
  error = null,
  limitReason = null,
  showVisibilityFilter = true,
  builderSessions = [],
  onStartBlank,
  onStartFromTemplate,
  onResumeBuilderSession,
  onBuilderSessionStopped,
}: LoopsListViewPresentationProps) {
  return (
    <LoopsPageLayout
      actions={
        <NewLoopButton
          label="New global loop"
          limitReason={limitReason}
          onClick={onStartBlank}
        />
      }
      footer={
        <>
          {builderSessions.map((session) => (
            <BuilderSessionRow
              key={session.taskId}
              session={session}
              onResume={onResumeBuilderSession}
              onStopped={onBuilderSessionStopped}
            />
          ))}
          <LoopBuilderComposer
            placeholder="What do you want automated across the whole project?"
            disabledReason={limitReason}
          />
        </>
      }
    >
      <LoopsListSection
        loops={loops}
        spaces={spaces}
        isLoading={isLoading}
        error={error}
        showScope
        showSpace
        showVisibility={showVisibilityFilter}
        emptyState={<LoopsEmptyState />}
      />

      <LoopTemplatesSection onSelect={onStartFromTemplate} />
    </LoopsPageLayout>
  );
}

function BuilderSessionRow({
  session,
  onResume,
  onStopped,
}: {
  session: LoopBuilderSession;
  onResume?: (taskId: string) => void;
  onStopped?: (taskId: string) => void;
}) {
  const [confirmStop, setConfirmStop] = useState(false);

  return (
    <div className="flex items-center gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2">
      <ChatCircleDotsIcon size={16} className="shrink-0 text-(--accent-11)" />
      <div className="flex min-w-0 flex-1 flex-col">
        <Text className="font-medium text-[12px] text-gray-10 uppercase tracking-wide">
          Builder in progress
        </Text>
        <Text className="truncate text-[13px] text-gray-12">
          {session.prompt}
        </Text>
      </div>
      <Button
        variant="soft"
        color="red"
        size="1"
        onClick={() => setConfirmStop(true)}
      >
        Stop
      </Button>
      <Button
        variant="soft"
        size="1"
        onClick={() => onResume?.(session.taskId)}
      >
        Resume
      </Button>
      {confirmStop ? (
        <StopCloudRunDialog
          open={confirmStop}
          taskId={session.taskId}
          title="Stop loop builder"
          buttonLabel="Stop builder"
          onOpenChange={setConfirmStop}
          onStopped={() => {
            toast.success("Builder stopped");
            onStopped?.(session.taskId);
          }}
        />
      ) : null}
    </div>
  );
}

import { ChatCircleDotsIcon, CloudIcon, PlusIcon } from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Button } from "@posthog/ui/primitives/Button";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderNav,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToNewLoop,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useLoopBuilderSessions } from "../hooks/useLoopBuilderSessions";
import { useLoopLimits, useLoops } from "../hooks/useLoops";
import {
  type LoopBuilderSession,
  useLoopBuilderSessionStore,
} from "../loopBuilderSessionStore";
import { useLoopDraftStore } from "../loopDraftStore";
import type { LoopTemplate } from "../loopTemplates";
import { LoopBuilderComposer } from "./LoopBuilderComposer";
import { LoopsEmptyNotice, LoopsSkeleton } from "./LoopFallbacks";
import { LoopRow } from "./LoopRow";
import { LoopsEmptyState } from "./LoopsEmptyState";
import { LoopTemplatesSection } from "./LoopTemplatesSection";

/** Copy shown when the project is at its loop cap. `max` comes from the backend so the number
 * never drifts from the limit the server actually enforces. */
function loopLimitReason(max: number): string {
  return `You've reached the limit of ${max} loops for this project. Delete one to add another.`;
}

const EMPTY_MEMBERS: UserBasic[] = [];
const EMPTY_BUILDER_SESSIONS: LoopBuilderSession[] = [];

const SECTION_PREVIEW_COUNT = 5;

function startBlankLoop(): void {
  useLoopDraftStore.getState().setPrefill(null);
  navigateToNewLoop();
}

function resumeBuilderSession(taskId: string): void {
  navigateToTaskDetail(taskId);
}

function removeBuilderSession(taskId: string): void {
  useLoopBuilderSessionStore.getState().removeSession(taskId);
}

function startLoopFromTemplate(template: LoopTemplate): void {
  useLoopDraftStore
    .getState()
    .setPrefill({ description: template.description, ...template.build() });
  navigateToNewLoop();
}

export function LoopsListView({
  headerContent = null,
}: {
  headerContent?: ReactNode;
}) {
  const { data: loops, isLoading, isError, error } = useLoops();
  const authenticatedClient = useOptionalAuthenticatedClient();
  const {
    data: currentUser,
    isLoading: currentUserLoading,
    isError: currentUserError,
    error: currentUserQueryError,
  } = useCurrentUser({ client: authenticatedClient });
  const limits = useLoopLimits();
  const limitReason =
    limits?.atLimit === true ? loopLimitReason(limits.max) : null;
  let listError: unknown = null;
  if (isError) {
    listError = error;
  } else if (currentUserError) {
    listError = currentUserQueryError;
  }

  // The standalone page names itself in-page and has no breadcrumb. When the
  // registry is hosted inside a space, its caller supplies that navigation
  // context instead.
  useSetHeaderContent(headerContent);

  const { sessions: builderSessions, isSettled: builderSessionsSettled } =
    useLoopBuilderSessions();

  const allLoops = loops ?? [];
  const personalLoops = allLoops.filter(
    (loop) => loop.visibility === "personal",
  );
  const teamLoops = allLoops.filter((loop) => loop.visibility === "team");
  const {
    members,
    isLoading: membersLoading,
    isError: membersError,
    isComplete: membersComplete,
  } = useOrgMembers({ enabled: teamLoops.length > 0 });

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
      loop_count: allLoops.length,
      personal_loop_count: personalLoops.length,
      team_loop_count: teamLoops.length,
      is_at_limit: limits?.atLimit ?? false,
      loop_limit: limits?.max,
      builder_session_count: builderSessions.length,
    });
  }, [
    isLoading,
    isError,
    builderSessionsSettled,
    allLoops.length,
    personalLoops.length,
    teamLoops.length,
    limits,
    builderSessions.length,
  ]);

  return (
    <LoopsListViewPresentation
      loops={allLoops}
      currentUserId={currentUser?.id ?? null}
      isLoading={isLoading || currentUserLoading}
      error={listError}
      limitReason={limitReason}
      members={members}
      membersLoading={membersLoading}
      membersError={membersError}
      membersComplete={membersComplete}
      builderSessions={builderSessions}
      onStartBlank={startBlankLoop}
      onStartFromTemplate={startLoopFromTemplate}
      onResumeBuilderSession={resumeBuilderSession}
      onBuilderSessionStopped={removeBuilderSession}
    />
  );
}

interface LoopsListViewPresentationProps {
  loops: LoopSchemas.Loop[];
  currentUserId?: number | null;
  isLoading?: boolean;
  error?: unknown;
  limitReason?: string | null;
  members?: UserBasic[];
  membersLoading?: boolean;
  membersError?: boolean;
  membersComplete?: boolean;
  builderSessions?: LoopBuilderSession[];
  onStartBlank: () => void;
  onStartFromTemplate: (template: LoopTemplate) => void;
  onResumeBuilderSession?: (taskId: string) => void;
  onBuilderSessionStopped?: (taskId: string) => void;
}

export function LoopsListViewPresentation({
  loops,
  currentUserId = null,
  isLoading = false,
  error = null,
  limitReason = null,
  members = EMPTY_MEMBERS,
  membersLoading = false,
  membersError = false,
  membersComplete = true,
  builderSessions = EMPTY_BUILDER_SESSIONS,
  onStartBlank,
  onStartFromTemplate,
  onResumeBuilderSession,
  onBuilderSessionStopped,
}: LoopsListViewPresentationProps) {
  const personalLoops = loops.filter(
    (loop) =>
      loop.visibility === "personal" ||
      (currentUserId !== null && loop.created_by_id === currentUserId),
  );
  const teamLoops = loops.filter(
    (loop) =>
      loop.visibility === "team" &&
      (currentUserId === null || loop.created_by_id !== currentUserId),
  );

  const createButton = (
    <Button
      variant="soft"
      color="gray"
      size="2"
      onClick={onStartBlank}
      disabled={limitReason != null}
      disabledReason={limitReason}
    >
      <PlusIcon size={14} />
      Create manually
    </Button>
  );

  // Only the loaded, non-empty list has tabs to show — the skeleton, the error
  // notice and the empty state all render without them.
  const hasTabs = !isLoading && !error && loops.length > 0;

  const body = (
    <>
      <div className="min-h-0 flex-1 overflow-auto">
        <Flex
          direction="column"
          gap="6"
          className="@container mx-auto w-full max-w-5xl px-8 py-8"
        >
          <Flex direction="column" gap="4">
            {isLoading ? (
              <LoopsSkeleton />
            ) : error ? (
              <LoopsEmptyNotice
                title="Couldn't load loops."
                hint={
                  error instanceof Error
                    ? error.message
                    : "The loops API returned an error."
                }
              />
            ) : loops.length > 0 ? (
              // Triggers live in the page header; only the panels sit here.
              <LoopTabPanels
                personalLoops={personalLoops}
                teamLoops={teamLoops}
                members={members}
                membersLoading={membersLoading}
                membersError={membersError}
                membersComplete={membersComplete}
              />
            ) : (
              <LoopsEmptyState />
            )}
          </Flex>

          <LoopTemplatesSection onSelect={onStartFromTemplate} />
        </Flex>
      </div>

      <div className="shrink-0">
        <Flex
          direction="column"
          gap="2"
          className="mx-auto w-full max-w-5xl px-8 pt-3 pb-6"
        >
          {builderSessions.map((session) => (
            <BuilderSessionRow
              key={session.taskId}
              session={session}
              onResume={onResumeBuilderSession}
              onStopped={onBuilderSessionStopped}
            />
          ))}
          <LoopBuilderComposer disabledReason={limitReason} />
        </Flex>
      </div>
    </>
  );

  // One Tabs root spanning header and body: the trigger strip sits in the
  // header's sub-nav, its panels stay down in the scrolling body.
  return (
    <Tabs
      defaultValue="personal"
      className="flex h-full min-h-0 flex-col gap-0"
    >
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Loops</PageHeaderTitle>
            <PageHeaderChip icon={<CloudIcon size={12} weight="fill" />}>
              Runs entirely in the cloud
            </PageHeaderChip>
            <PageHeaderActions>{createButton}</PageHeaderActions>
          </PageHeaderTitleRow>
          <PageHeaderDescription>
            Put your work on autopilot. Loops run on a schedule, on an API call,
            or when something happens on GitHub. You can finally close the
            laptop!
          </PageHeaderDescription>
        </PageHeaderHeading>
        {hasTabs && (
          <PageHeaderNav>
            <LoopTabsList
              personalCount={personalLoops.length}
              teamCount={teamLoops.length}
            />
          </PageHeaderNav>
        )}
      </PageHeader>
      {body}
    </Tabs>
  );
}

/** The trigger strip. Rendered inside the page header. */
function LoopTabsList({
  personalCount,
  teamCount,
}: {
  personalCount: number;
  teamCount: number;
}) {
  return (
    <TabsList variant="line" className="h-auto gap-0.5">
      <TabsTrigger value="personal" className="gap-1.5 px-2.5 py-2">
        <span className="font-medium text-[13px]">
          My loops ({personalCount})
        </span>
      </TabsTrigger>
      <TabsTrigger value="team" className="gap-1.5 px-2.5 py-2">
        <span className="font-medium text-[13px]">
          Team loops ({teamCount})
        </span>
      </TabsTrigger>
    </TabsList>
  );
}

/** The panels. Always in the scrolling body, wherever the triggers live. */
function LoopTabPanels({
  personalLoops,
  teamLoops,
  members,
  membersLoading,
  membersError,
  membersComplete,
}: {
  personalLoops: LoopSchemas.Loop[];
  teamLoops: LoopSchemas.Loop[];
  members: UserBasic[];
  membersLoading: boolean;
  membersError: boolean;
  membersComplete: boolean;
}) {
  return (
    <>
      <TabsContent value="personal">
        {personalLoops.length > 0 ? (
          <LoopListSection
            loops={personalLoops}
            members={members}
            membersLoading={membersLoading}
            membersError={membersError}
            membersComplete={membersComplete}
          />
        ) : (
          <LoopsEmptyState />
        )}
      </TabsContent>
      <TabsContent value="team">
        {teamLoops.length > 0 ? (
          <LoopListSection
            loops={teamLoops}
            members={members}
            membersLoading={membersLoading}
            membersError={membersError}
            membersComplete={membersComplete}
          />
        ) : (
          <LoopsEmptyNotice
            title="No team loops yet."
            hint="Loops shared with your team will appear here."
          />
        )}
      </TabsContent>
    </>
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
    <Flex
      align="center"
      gap="3"
      className="rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-3 py-2"
    >
      <ChatCircleDotsIcon size={16} className="shrink-0 text-(--accent-11)" />
      <Flex direction="column" className="min-w-0 flex-1">
        <Text className="font-medium text-[12px] text-gray-10 uppercase tracking-wide">
          Builder in progress
        </Text>
        <Text className="truncate text-[13px] text-gray-12">
          {session.prompt}
        </Text>
      </Flex>
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
    </Flex>
  );
}

function LoopListSection({
  loops,
  members = EMPTY_MEMBERS,
  membersLoading = false,
  membersError = false,
  membersComplete = true,
}: {
  loops: LoopSchemas.Loop[];
  members?: UserBasic[];
  membersLoading?: boolean;
  membersError?: boolean;
  membersComplete?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const visibleLoops = expanded ? loops : loops.slice(0, SECTION_PREVIEW_COUNT);

  return (
    <Flex direction="column" gap="3">
      <Flex direction="column" gap="2">
        {visibleLoops.map((loop) => (
          <LoopRow
            key={loop.id}
            loop={loop}
            creator={members.find((member) => member.id === loop.created_by_id)}
            creatorLoading={membersLoading}
            creatorError={membersError}
            creatorLookupComplete={membersComplete}
          />
        ))}
      </Flex>
      {loops.length > SECTION_PREVIEW_COUNT ? (
        <Button
          variant="ghost"
          color="gray"
          size="1"
          className="w-fit"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show fewer" : `Show all ${loops.length}`}
        </Button>
      ) : null}
    </Flex>
  );
}

import { CloudIcon, PlusIcon } from "@phosphor-icons/react";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Button } from "@posthog/ui/primitives/Button";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { navigateToNewLoop } from "@posthog/ui/router/navigationBridge";
import { Flex, Heading, Text } from "@radix-ui/themes";
import { type ReactNode, useMemo } from "react";
import { LoopBuilderComposer } from "../../loops/components/LoopBuilderComposer";
import {
  LoopsEmptyNotice,
  LoopsSkeleton,
} from "../../loops/components/LoopFallbacks";
import { LoopRow } from "../../loops/components/LoopRow";
import { LoopsEmptyState } from "../../loops/components/LoopsEmptyState";
import { LoopsListView } from "../../loops/components/LoopsListView";
import { LoopTemplatesSection } from "../../loops/components/LoopTemplatesSection";
import { useLoopLimits, useLoops } from "../../loops/hooks/useLoops";
import { useLoopDraftStore } from "../../loops/loopDraftStore";
import { defaultLoopContextOutputs } from "../../loops/loopFormTypes";
import type { LoopTemplate } from "../../loops/loopTemplates";
import { useChannels } from "../hooks/useChannels";
import { useOrgMembers } from "../hooks/useOrgMembers";
import { PERSONAL_CHANNEL_NAME } from "../hooks/useTaskChannels";

function contextQuickStarts(name: string): { label: string; prompt: string }[] {
  return [
    {
      label: "Digest to feed",
      prompt: `On a schedule, post a short digest to #${name}'s feed summarizing `,
    },
    {
      label: "Keep context.md current",
      prompt: `On a schedule, update #${name}'s context.md with the latest `,
    },
    {
      label: "Refresh a canvas",
      prompt: `On a schedule, refresh a canvas in #${name} with `,
    },
    {
      label: "Watch and report",
      prompt: `Watch for changes in `,
    },
  ];
}

/** The "Loops" tab of a context: same layout as the main Loops page (list on top, agent
 * composer pinned at the bottom), but the build surface is tuned to automations that feed
 * this context. `channelId` is the desktop folder id, matching `context_target.folder_id`. */
export function WebsiteChannelLoops({ channelId }: { channelId: string }) {
  const { channels, isLoading } = useChannels();
  const channel = channels.find((candidate) => candidate.id === channelId);
  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="loops" />,
    [channelId],
  );

  // Don't mount the scoped scene while the route's space is unresolved. In
  // particular, that would flash a raw-id empty state for Personal before the
  // channel query identifies it as the project-level loops registry.
  if (isLoading && !channel) {
    return <ChannelLoopsLoading headerContent={headerContent} />;
  }

  // The Personal space is the project-level home for loops in the spaces
  // layout. API-created and other unattached loops have no context_target, so
  // rendering the space-scoped list here incorrectly produces the global
  // "Create your first loop" empty state while those loops already exist.
  if (channel?.name === PERSONAL_CHANNEL_NAME) {
    return <LoopsListView headerContent={headerContent} />;
  }

  return (
    <SpaceAttachedLoops
      channelId={channelId}
      contextName={channel?.name ?? channelId}
    />
  );
}

function ChannelLoopsLoading({ headerContent }: { headerContent: ReactNode }) {
  useSetHeaderContent(headerContent);
  return (
    <div className="mx-auto w-full max-w-5xl px-8 py-8">
      <LoopsSkeleton />
    </div>
  );
}

function SpaceAttachedLoops({
  channelId,
  contextName,
}: {
  channelId: string;
  contextName: string;
}) {
  const { data: loops, isLoading, isError } = useLoops();
  const spacesLayout = useChannelsLayout();
  const limits = useLoopLimits();
  const limitReason =
    limits?.atLimit === true
      ? `You've reached the limit of ${limits.max} loops for this project. Delete one to add another.`
      : null;

  useSetHeaderContent(
    useMemo(
      () => <ChannelHeader channelId={channelId} page="loops" />,
      [channelId],
    ),
  );

  const attachedLoops = useMemo(
    () =>
      (loops ?? []).filter(
        (loop) => loop.context_target?.folder_id === channelId,
      ),
    [loops, channelId],
  );
  const {
    members,
    isLoading: membersLoading,
    isError: membersError,
    isComplete: membersComplete,
  } = useOrgMembers({ enabled: attachedLoops.length > 0 });

  const startBlank = () => {
    useLoopDraftStore.getState().setPrefill({
      contextTarget: {
        folderId: channelId,
        name: contextName,
        outputs: defaultLoopContextOutputs(),
      },
    });
    navigateToNewLoop();
  };

  const startFromTemplate = (template: LoopTemplate) => {
    useLoopDraftStore.getState().setPrefill({
      description: template.description,
      ...template.build(),
      contextTarget: {
        folderId: channelId,
        name: contextName,
        outputs: defaultLoopContextOutputs(),
      },
    });
    navigateToNewLoop();
  };

  const title = `Automate #${contextName}`;
  const description =
    "Put your work on autopilot. Loops run on a schedule, on an API call, or when something happens on GitHub. You can finally close the laptop!";
  const createButton = (
    <Button
      variant="soft"
      color="gray"
      size="2"
      onClick={startBlank}
      disabled={limitReason != null}
      disabledReason={limitReason}
    >
      <PlusIcon size={14} />
      Create manually
    </Button>
  );

  return (
    <Flex direction="column" className="h-full min-h-0">
      {/* The shared page header ships with the spaces layout; without it the
          in-container title block below is used. Delete that branch when the
          layout flag graduates. */}
      {spacesLayout && (
        <PageHeader>
          <PageHeaderHeading>
            <PageHeaderTitleRow>
              <PageHeaderTitle>{title}</PageHeaderTitle>
              <PageHeaderChip icon={<CloudIcon size={12} weight="fill" />}>
                Runs entirely in the cloud
              </PageHeaderChip>
              <PageHeaderActions>{createButton}</PageHeaderActions>
            </PageHeaderTitleRow>
            <PageHeaderDescription>{description}</PageHeaderDescription>
          </PageHeaderHeading>
        </PageHeader>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <Flex
          direction="column"
          gap="6"
          className="@container mx-auto w-full max-w-5xl px-8 py-8"
        >
          {!spacesLayout && (
            <div className="flex @min-[640px]:flex-row flex-col items-start @min-[640px]:items-center justify-between gap-3">
              <Flex
                direction="column"
                gap="1"
                className="w-full min-w-0 @min-[640px]:max-w-[70%]"
              >
                <Flex align="center" gap="2" wrap="wrap">
                  <Heading className="font-bold text-2xl">{title}</Heading>
                  <Flex
                    align="center"
                    className="gap-1.5 rounded-full bg-(--accent-a3) px-2.5 py-1"
                  >
                    <CloudIcon
                      size={12}
                      weight="fill"
                      className="text-(--accent-11)"
                    />
                    <Text className="whitespace-nowrap font-medium text-(--accent-11) text-[11px]">
                      Runs entirely in the cloud
                    </Text>
                  </Flex>
                </Flex>
                <Text color="gray" className="text-sm">
                  {description}
                </Text>
              </Flex>
              {createButton}
            </div>
          )}

          {isLoading ? (
            <LoopsSkeleton />
          ) : isError ? (
            <LoopsEmptyNotice
              title="Couldn't load loops"
              hint="The loops API returned an error. Try again in a moment."
            />
          ) : attachedLoops.length > 0 ? (
            <Flex direction="column" gap="3">
              <Text className="font-medium text-[12px] text-gray-10 uppercase tracking-wide">
                Attached loops
              </Text>
              <Flex direction="column" gap="2">
                {attachedLoops.map((loop) => (
                  <LoopRow
                    key={loop.id}
                    loop={loop}
                    creator={members.find(
                      (member) => member.id === loop.created_by_id,
                    )}
                    creatorLoading={membersLoading}
                    creatorError={membersError}
                    creatorLookupComplete={membersComplete}
                  />
                ))}
              </Flex>
            </Flex>
          ) : (
            <LoopsEmptyState contextName={contextName} />
          )}

          <LoopTemplatesSection onSelect={startFromTemplate} />
        </Flex>
      </div>

      <div className="shrink-0">
        <Flex
          direction="column"
          gap="2"
          className="mx-auto w-full max-w-5xl px-8 pt-3 pb-6"
        >
          <LoopBuilderComposer
            context={{ folderId: channelId, name: contextName }}
            placeholder={`What should #${contextName} keep an eye on?`}
            quickStarts={contextQuickStarts(contextName)}
            disabledReason={limitReason}
          />
        </Flex>
      </div>
    </Flex>
  );
}

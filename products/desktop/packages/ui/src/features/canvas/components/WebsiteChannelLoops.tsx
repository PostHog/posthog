import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { type ReactNode, useMemo } from "react";
import { LoopBuilderComposer } from "../../loops/components/LoopBuilderComposer";
import { LoopsSkeleton } from "../../loops/components/LoopFallbacks";
import { LoopsEmptyState } from "../../loops/components/LoopsEmptyState";
import { LoopsListSection } from "../../loops/components/LoopsListSection";
import { LoopTemplatesSection } from "../../loops/components/LoopTemplatesSection";
import { NewLoopButton } from "../../loops/components/NewLoopButton";
import { useLoopLimitReason, useLoops } from "../../loops/hooks/useLoops";
import { useLoopDraftStore } from "../../loops/loopDraftStore";
import { defaultLoopContextOutputs } from "../../loops/loopFormTypes";
import type { LoopTemplate } from "../../loops/loopTemplates";
import { openNewLoop } from "../../loops/loopWizardDialogStore";
import { useChannels } from "../hooks/useChannels";

function contextQuickStarts(name: string): { label: string; prompt: string }[] {
  const contextReference = channelDisplayReference(name);
  return [
    {
      label: "Digest to feed",
      prompt: `On a schedule, post a short digest to ${contextReference}'s feed summarizing `,
    },
    {
      label: "Keep context.md current",
      prompt: `On a schedule, update ${contextReference}'s context.md with the latest `,
    },
    {
      label: "Refresh a canvas",
      prompt: `On a schedule, refresh a canvas in ${contextReference} with `,
    },
    {
      label: "Watch and report",
      prompt: `Watch for changes in `,
    },
  ];
}

export function WebsiteChannelLoops({ channelId }: { channelId: string }) {
  const { channels, isLoading } = useChannels();
  const channel = channels.find((candidate) => candidate.id === channelId);
  const headerContent = useMemo(
    () => <ChannelHeader channelId={channelId} page="loops" />,
    [channelId],
  );

  if (isLoading && !channel) {
    return <ChannelLoopsLoading headerContent={headerContent} />;
  }

  return (
    <SpaceAttachedLoops
      channelId={channelId}
      contextName={channel?.name ?? channelId}
    />
  );
}

function ChannelLoopsLoading({ headerContent }: { headerContent: ReactNode }) {
  useSetHeaderContent(headerContent, !useWorkLayout());
  return (
    <div className="mx-auto w-full max-w-6xl px-8 py-8">
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
  const { data: loops, isLoading, error } = useLoops();
  const { channels: spaces } = useChannels();
  const workflowBacked = useLoopsHogFlowsEnabled();
  const limitReason = useLoopLimitReason();

  const workLayout = useWorkLayout();
  useSetHeaderContent(
    useMemo(
      () => <ChannelHeader channelId={channelId} page="loops" />,
      [channelId],
    ),
    !workLayout,
  );

  const attachedLoops = useMemo(
    () =>
      (loops ?? []).filter(
        (loop) => loop.context_target?.channel_id === channelId,
      ),
    [loops, channelId],
  );
  const contextTarget = {
    folderId: channelId,
    name: contextName,
    outputs: defaultLoopContextOutputs(),
  };
  const startBlank = () => {
    useLoopDraftStore.getState().setPrefill({ contextTarget });
    openNewLoop();
  };
  const startFromTemplate = (template: LoopTemplate) => {
    useLoopDraftStore.getState().setPrefill({
      description: template.description,
      ...template.build(),
      contextTarget,
    });
    openNewLoop();
  };

  const contextReference = channelDisplayReference(contextName);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitleRow>
            <PageHeaderTitle>Loops</PageHeaderTitle>
            <PageHeaderActions>
              <NewLoopButton
                label="New loop"
                limitReason={limitReason}
                onClick={startBlank}
              />
            </PageHeaderActions>
          </PageHeaderTitleRow>
        </PageHeaderHeading>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="@container mx-auto flex w-full max-w-6xl flex-col gap-8 px-8 pt-6 pb-8">
          <LoopsListSection
            loops={attachedLoops}
            spaces={spaces}
            isLoading={isLoading}
            error={error}
            showScope={false}
            showSpace={false}
            showVisibility={!workflowBacked}
            emptyState={<LoopsEmptyState contextName={contextName} />}
          />

          <LoopTemplatesSection onSelect={startFromTemplate} />
        </div>
      </div>

      <div className="shrink-0">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-8 pt-3 pb-6">
          <LoopBuilderComposer
            context={{ folderId: channelId, name: contextName }}
            placeholder={`What should ${contextReference} keep an eye on?`}
            quickStarts={contextQuickStarts(contextName)}
            disabledReason={limitReason}
          />
        </div>
      </div>
    </div>
  );
}

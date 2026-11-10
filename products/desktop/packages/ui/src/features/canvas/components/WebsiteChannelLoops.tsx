import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { type ReactNode, useMemo } from "react";
import { LoopBuilderComposer } from "../../loops/components/LoopBuilderComposer";
import { LoopsSkeleton } from "../../loops/components/LoopFallbacks";
import { LoopsEmptyState } from "../../loops/components/LoopsEmptyState";
import { LoopsListSection } from "../../loops/components/LoopsListSection";
import { LoopsPageLayout } from "../../loops/components/LoopsPageLayout";
import { LoopTemplatesSection } from "../../loops/components/LoopTemplatesSection";
import { NewLoopButton } from "../../loops/components/NewLoopButton";
import { useLoops } from "../../loops/hooks/useLoops";
import { startNewLoop } from "../../loops/loopWizardDialogStore";
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
  const contextTarget = { folderId: channelId, name: contextName };

  const contextReference = channelDisplayReference(contextName);
  return (
    <LoopsPageLayout
      actions={
        <NewLoopButton
          label="New loop"
          onClick={() => startNewLoop({ context: contextTarget })}
        />
      }
      footer={
        <LoopBuilderComposer
          context={{ folderId: channelId, name: contextName }}
          placeholder={`What should ${contextReference} keep an eye on?`}
          quickStarts={contextQuickStarts(contextName)}
        />
      }
    >
      <LoopsListSection
        loops={attachedLoops}
        spaces={spaces}
        isLoading={isLoading}
        error={error}
        showScope={false}
        showSpace={false}
        emptyState={<LoopsEmptyState contextName={contextName} />}
      />

      <LoopTemplatesSection
        onSelect={(template) =>
          startNewLoop({ template, context: contextTarget })
        }
      />
    </LoopsPageLayout>
  );
}

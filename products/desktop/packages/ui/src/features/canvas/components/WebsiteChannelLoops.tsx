import { CloudIcon, PlusIcon } from "@phosphor-icons/react";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Button } from "@posthog/ui/primitives/Button";
import { navigateToNewLoop } from "@posthog/ui/router/navigationBridge";
import { Flex, Heading, Text } from "@radix-ui/themes";
import { useMemo } from "react";
import { LoopBuilderComposer } from "../../loops/components/LoopBuilderComposer";
import {
  LoopsEmptyNotice,
  LoopsSkeleton,
} from "../../loops/components/LoopFallbacks";
import { LoopRow } from "../../loops/components/LoopRow";
import { LoopsEmptyState } from "../../loops/components/LoopsEmptyState";
import { useLoopLimits, useLoops } from "../../loops/hooks/useLoops";
import { useLoopDraftStore } from "../../loops/loopDraftStore";
import { defaultLoopContextOutputs } from "../../loops/loopFormTypes";
import { useChannels } from "../hooks/useChannels";

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
  const { data: loops, isLoading, isError } = useLoops();
  const limits = useLoopLimits();
  const limitReason =
    limits?.atLimit === true
      ? `You've reached the limit of ${limits.max} loops for this project. Delete one to add another.`
      : null;
  const { channels } = useChannels();
  const channel = channels.find((c) => c.id === channelId);
  const contextName = channel?.name ?? channelId;

  useSetHeaderContent(
    useMemo(() => <ChannelHeader channelId={channelId} />, [channelId]),
  );

  const attachedLoops = useMemo(
    () =>
      (loops ?? []).filter(
        (loop) => loop.context_target?.folder_id === channelId,
      ),
    [loops, channelId],
  );

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

  return (
    <Flex direction="column" className="h-full min-h-0">
      <div className="min-h-0 flex-1 overflow-auto">
        <Flex
          direction="column"
          gap="6"
          className="@container mx-auto w-full max-w-3xl px-8 py-8"
        >
          <div className="flex @min-[640px]:flex-row flex-col items-start @min-[640px]:items-center justify-between gap-3">
            <Flex
              direction="column"
              gap="1"
              className="w-full min-w-0 @min-[640px]:max-w-[70%]"
            >
              <Flex align="center" gap="2" wrap="wrap">
                <Heading className="font-bold text-2xl">
                  Automate #{contextName}
                </Heading>
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
                Build a loop that posts its runs to this context's feed, or
                keeps its context.md or a canvas up to date.
              </Text>
            </Flex>
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
          </div>

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
                  <LoopRow key={loop.id} loop={loop} />
                ))}
              </Flex>
            </Flex>
          ) : (
            <LoopsEmptyState
              contextName={contextName}
              onCreate={startBlank}
              disabledReason={limitReason}
            />
          )}
        </Flex>
      </div>

      <div className="shrink-0">
        <Flex
          direction="column"
          gap="2"
          className="mx-auto w-full max-w-3xl px-8 pb-6"
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

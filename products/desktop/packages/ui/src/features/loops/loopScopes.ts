import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  type ChannelType,
  channelDisplayName,
  PERSONAL_CHANNEL_LABEL,
} from "@posthog/core/canvas/channelName";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";

export type LoopSpace = Pick<Channel, "id" | "name" | "channelType">;

export type LoopScope =
  | { kind: "global"; label: "Global" }
  | {
      kind: "space";
      channelId: string;
      label: string;
      channelType: ChannelType | undefined;
      available: boolean;
    };

export function resolveLoopScope(
  loop: LoopSchemas.Loop,
  spaces: LoopSpace[],
): LoopScope {
  const target = loop.context_target;
  if (!target) return { kind: "global", label: "Global" };
  const space = spaces.find((candidate) => candidate.id === target.channel_id);
  const storedLabel = channelDisplayName(target.name);
  const teammatesPersonalSpace =
    space === undefined && storedLabel === PERSONAL_CHANNEL_LABEL;
  return {
    kind: "space",
    channelId: target.channel_id,
    label: space
      ? channelDisplayName(space.name)
      : teammatesPersonalSpace
        ? "Teammate's personal space"
        : storedLabel,
    channelType:
      space?.channelType ?? (teammatesPersonalSpace ? "personal" : undefined),
    available: space !== undefined,
  };
}

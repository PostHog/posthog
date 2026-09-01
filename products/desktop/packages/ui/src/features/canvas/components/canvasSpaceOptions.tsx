import type { CanvasMultiSelectOption } from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";

function optionForChannel(channel: Channel): CanvasMultiSelectOption {
  const personal = channel.channelType === "personal";
  return {
    value: channel.id,
    label: personal ? "personal" : channel.name,
    icon: channelGlyph(channel.name, {
      size: 16,
      personal,
      space: true,
      className: "shrink-0 text-muted-foreground",
    }),
  };
}

export function buildCanvasSpaceOptions(
  channels: readonly Channel[],
): CanvasMultiSelectOption[] {
  const personal = channels.filter(
    (channel) => channel.channelType === "personal",
  );
  const shared = channels.filter(
    (channel) => channel.channelType !== "personal",
  );
  return [
    ...personal.map(optionForChannel),
    { value: null, label: "Every space" },
    ...shared.map(optionForChannel),
  ];
}

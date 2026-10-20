import { channelDisplayLabel } from "@posthog/core/canvas/channelName";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useChannels } from "../../canvas/hooks/useChannels";
import type { LoopContextTargetDraft } from "../loopFormTypes";

const NOT_ATTACHED_VALUE = "__none__";

interface LoopContextFieldsProps {
  value: LoopContextTargetDraft | null;
  onChange: (value: LoopContextTargetDraft | null) => void;
  disabled?: boolean;
}

export function LoopContextFields({
  value,
  onChange,
  disabled,
}: LoopContextFieldsProps) {
  const { channels } = useChannels();

  const selectContext = (folderId: string) => {
    if (folderId === NOT_ATTACHED_VALUE) {
      onChange(null);
      return;
    }
    const channel = channels.find((c) => c.id === folderId);
    if (!channel) return;
    onChange({ folderId: channel.id, name: channel.name });
  };

  const contextOptions = [
    { value: NOT_ATTACHED_VALUE, label: "Not attached to a channel" },
    ...channels.map((channel) => ({
      value: channel.id,
      label: channelDisplayLabel(channel.name, channel.channelType),
    })),
  ];

  return (
    <SettingsOptionSelect
      value={value?.folderId ?? NOT_ATTACHED_VALUE}
      options={contextOptions}
      disabled={disabled}
      size="lg"
      ariaLabel="Context channel"
      onValueChange={selectContext}
    />
  );
}

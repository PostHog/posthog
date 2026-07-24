import type { LoopSchemas } from "@posthog/api-client/loops";
import { Switch } from "@posthog/quill";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { Flex, Text } from "@radix-ui/themes";
import { useChannels } from "../../canvas/hooks/useChannels";
import { useDashboards } from "../../canvas/hooks/useDashboards";
import {
  defaultLoopContextOutputs,
  type LoopContextTargetDraft,
} from "../loopFormTypes";

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
  const { dashboards } = useDashboards(value?.folderId);
  const hasCanvases = dashboards.length > 0;

  const selectContext = (folderId: string) => {
    if (folderId === NOT_ATTACHED_VALUE) {
      onChange(null);
      return;
    }
    const channel = channels.find((c) => c.id === folderId);
    if (!channel) return;
    // Carry the output toggles across contexts, but drop a canvas that belonged to the old one.
    onChange({
      folderId: channel.id,
      name: channel.name,
      outputs: {
        ...(value?.outputs ?? defaultLoopContextOutputs()),
        canvas_id: null,
      },
    });
  };

  const patchOutputs = (outputs: Partial<LoopSchemas.LoopContextOutputs>) => {
    if (!value) return;
    onChange({ ...value, outputs: { ...value.outputs, ...outputs } });
  };

  const contextOptions = [
    { value: NOT_ATTACHED_VALUE, label: "Not attached to a channel" },
    ...channels.map((channel) => ({
      value: channel.id,
      label: `#${channel.name}`,
    })),
  ];

  return (
    <Flex direction="column" gap="3">
      <SettingsOptionSelect
        value={value?.folderId ?? NOT_ATTACHED_VALUE}
        options={contextOptions}
        disabled={disabled}
        size="lg"
        ariaLabel="Context channel"
        onValueChange={selectContext}
      />

      {value ? (
        <Flex
          direction="column"
          gap="3"
          className="rounded-(--radius-2) border border-border bg-(--gray-1) p-3"
        >
          <ToggleRow
            title="Show runs in the feed"
            description="Each run appears as a card in this context's feed."
            checked={value.outputs.post_to_feed}
            disabled={disabled}
            onChange={(checked) => patchOutputs({ post_to_feed: checked })}
          />
          <ToggleRow
            title="Keep context.md updated"
            description="Each run reads this context's context.md and republishes it with the latest state."
            checked={value.outputs.update_context}
            disabled={disabled}
            onChange={(checked) => patchOutputs({ update_context: checked })}
          />
          <ToggleRow
            title="Maintain a canvas"
            description={
              hasCanvases
                ? "Each run rewrites a canvas in this context with fresh content."
                : "This context has no canvases yet. Create one to keep it up to date here."
            }
            checked={!!value.outputs.canvas_id}
            disabled={disabled || !hasCanvases}
            onChange={(checked) =>
              patchOutputs({
                canvas_id: checked ? (dashboards[0]?.id ?? null) : null,
              })
            }
          />
          {value.outputs.canvas_id ? (
            <SettingsOptionSelect
              value={value.outputs.canvas_id}
              options={dashboards.map((dashboard) => ({
                value: dashboard.id,
                label: dashboard.name,
              }))}
              disabled={disabled}
              size="lg"
              ariaLabel="Canvas"
              onValueChange={(canvasId) =>
                patchOutputs({ canvas_id: canvasId })
              }
            />
          ) : null}
        </Flex>
      ) : null}
    </Flex>
  );
}

function ToggleRow({
  title,
  description,
  checked,
  onChange,
  disabled,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <Flex align="center" justify="between" gap="3">
      <Flex direction="column" gap="0" className="min-w-0">
        <Text className="font-medium text-[13px] text-gray-12">{title}</Text>
        <Text className="text-[12px] text-gray-10">{description}</Text>
      </Flex>
      <Switch
        checked={checked}
        disabled={disabled}
        aria-label={title}
        onCheckedChange={onChange}
      />
    </Flex>
  );
}

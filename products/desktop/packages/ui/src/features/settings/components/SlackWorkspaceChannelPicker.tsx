import type { Integration } from "@posthog/core/integrations/selectors";
import { SlackChannelCombobox } from "@posthog/ui/features/settings/components/SlackChannelCombobox";
import { SlackWorkspaceSelect } from "@posthog/ui/features/settings/components/SlackWorkspaceSelect";
import { Flex } from "@radix-ui/themes";

interface SlackWorkspaceChannelPickerProps {
  integrations: Integration[];
  integrationId: number | null;
  channelValue: string | null;
  onIntegrationChange: (integrationId: number) => void;
  onChannelChange: (channelTarget: string | null) => void;
  channelAriaLabel: string;
  offLabel?: string;
  disabled?: boolean;
  modal?: boolean;
}

export function SlackWorkspaceChannelPicker({
  integrations,
  integrationId,
  channelValue,
  onIntegrationChange,
  onChannelChange,
  channelAriaLabel,
  offLabel,
  disabled,
  modal,
}: SlackWorkspaceChannelPickerProps) {
  return (
    <Flex align="center" gap="2" wrap="wrap">
      {integrations.length > 1 ? (
        <SlackWorkspaceSelect
          integrations={integrations}
          value={integrationId}
          disabled={disabled}
          className="min-w-[200px] max-w-[240px]"
          onValueChange={onIntegrationChange}
        />
      ) : null}
      <SlackChannelCombobox
        key={integrationId}
        integrationId={integrationId}
        value={channelValue}
        onChange={onChannelChange}
        offLabel={offLabel}
        ariaLabel={channelAriaLabel}
        disabled={disabled}
        modal={modal}
      />
    </Flex>
  );
}

import type { Integration } from "@posthog/core/integrations/selectors";
import { getSlackIntegrationLabel } from "@posthog/core/settings/slackNotificationTarget";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";

interface SlackWorkspaceSelectProps {
  integrations: Integration[];
  value: number | null;
  onValueChange: (integrationId: number) => void;
  disabled?: boolean;
  className?: string;
}

export function SlackWorkspaceSelect({
  integrations,
  value,
  onValueChange,
  disabled,
  className,
}: SlackWorkspaceSelectProps) {
  return (
    <SettingsOptionSelect
      value={value ? String(value) : ""}
      options={integrations.map((integration) => ({
        value: String(integration.id),
        label: getSlackIntegrationLabel(integration),
      }))}
      ariaLabel="Slack workspace"
      placeholder="Select workspace"
      disabled={disabled}
      className={className}
      onValueChange={(nextValue) => {
        const integrationId = Number(nextValue);
        if (Number.isFinite(integrationId)) {
          onValueChange(integrationId);
        }
      }}
    />
  );
}

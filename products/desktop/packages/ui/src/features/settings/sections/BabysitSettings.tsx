import { GitPullRequest } from "@phosphor-icons/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";
import {
  type BabysitMode,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback } from "react";

const BABYSIT_MODE_OPTIONS: { value: BabysitMode; label: string }[] = [
  { value: "ask", label: "Ask every time" },
  { value: "auto", label: "Auto-approved" },
  { value: "always", label: "Babysitting" },
  { value: "never", label: "Never" },
];

const MODE_DESCRIPTIONS: Record<BabysitMode, string> = {
  ask: 'Show a prompt with the failing checks and review comments. The agent only acts when you click "Start babysitting".',
  auto: "The agent fixes failing checks and review comments on its own, up to 3 follow-up turns.",
  always:
    "Like auto, but the agent keeps watching the PR until it merges or closes, with no idle wait or turn cap.",
  never:
    "The agent does not watch the PR after opening it. No follow-up turns run.",
};

/**
 * The PR babysitting setting: what the agent does after it opens a pull request
 * and the CI starts running. See BabysitMode in settingsStore for the modes.
 */
export function BabysitSettings() {
  const babysitMode = useSettingsStore((s) => s.babysitMode);
  const setBabysitMode = useSettingsStore((s) => s.setBabysitMode);

  const handleChange = useCallback(
    (value: BabysitMode) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "babysit_mode",
        new_value: value,
        old_value: babysitMode,
      });
      setBabysitMode(value);
    },
    [babysitMode, setBabysitMode],
  );

  return (
    <SettingsSection
      label="PR babysitting"
      description="What the agent does after it opens a pull request and the CI starts running."
    >
      <SettingsCard>
        <SettingsCardRow
          label="When CI needs attention"
          description={MODE_DESCRIPTIONS[babysitMode]}
          stacked
        >
          <SettingsSegmented
            ariaLabel="PR babysitting mode"
            value={babysitMode}
            options={BABYSIT_MODE_OPTIONS}
            onValueChange={(value) => handleChange(value as BabysitMode)}
          />
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}

// Re-exported for the composer indicator's tooltip label.
export const BABYSIT_MODE_LABELS: Record<BabysitMode, string> = {
  ask: "Ask every time",
  auto: "Auto-approved",
  always: "Babysitting",
  never: "Never",
};

export const BabysitModeIcon = GitPullRequest;

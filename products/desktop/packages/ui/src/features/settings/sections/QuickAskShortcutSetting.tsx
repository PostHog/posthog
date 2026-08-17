import { useServiceOptional } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { QUICK_ASK_SHORTCUT_PRESETS } from "@posthog/shared/quick-ask-shortcuts";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { track } from "@posthog/ui/shell/analytics";
import { Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";

const IS_MAC =
  typeof navigator !== "undefined" && navigator.platform.startsWith("Mac");

const OPTIONS = QUICK_ASK_SHORTCUT_PRESETS.map((preset) => ({
  value: preset.accelerator,
  label: IS_MAC ? preset.macLabel : preset.otherLabel,
}));

/**
 * Global shortcut picker for the quick-ask panel. Renders nothing on hosts
 * without the panel (no bound client, or the host reports it disabled).
 */
export function QuickAskShortcutSetting() {
  const client = useServiceOptional<QuickAskSettingsClient>(
    QUICK_ASK_SETTINGS_CLIENT,
  );
  const [state, setState] = useState<QuickAskState | null>(null);

  useEffect(() => {
    if (!client) return;
    let active = true;
    client.getState().then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [client]);

  if (!client || !state?.enabled) {
    return null;
  }

  const handleChange = (accelerator: string): void => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "quick_ask_shortcut",
      new_value: accelerator,
      old_value: state.shortcut,
    });
    void client.setShortcut(accelerator).then(setState);
  };

  return (
    <SettingRow
      label="Ask PostHog anywhere"
      description={
        state.registered
          ? "Summons the PostHog AI pill at your cursor, over any app."
          : "This shortcut is taken by another app. Pick a different one."
      }
    >
      <div className="flex flex-col items-end gap-1">
        <SettingsOptionSelect
          value={state.shortcut}
          options={OPTIONS}
          onValueChange={handleChange}
          ariaLabel="Quick ask shortcut"
          className="w-44"
        />
        {!state.registered && (
          <Text color="red" className="text-xs">
            Not active
          </Text>
        )}
      </div>
    </SettingRow>
  );
}

import { PencilSimple } from "@phosphor-icons/react";
import { useServiceOptional } from "@posthog/di/react";
import { Button } from "@posthog/quill";
import { formatAccelerator } from "@posthog/shared/quick-ask-shortcuts";
import { KeyboardShortcutsList } from "@posthog/ui/features/command/KeyboardShortcutsSheet";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { useEffect, useState } from "react";

const IS_MAC = globalThis.navigator?.platform.startsWith("Mac") ?? false;

/** Read-only mention of the quick-ask shortcut; editing lives on its page. */
function QuickAskShortcutRow() {
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

  if (!client || !state?.enabled || !state.active) return null;

  return (
    <SettingRow
      label="Ask PostHog anywhere"
      description="Summons the quick-ask panel over any app."
    >
      <span className="inline-flex items-center gap-2">
        <span className="font-mono text-(--gray-12) text-sm">
          {formatAccelerator(state.shortcut, IS_MAC)}
        </span>
        <Button
          variant="link-muted"
          size="sm"
          aria-label="Change in quick ask settings"
          title="Change in quick ask settings"
          onClick={() => openSettings("quick-ask")}
        >
          <PencilSimple size={14} />
        </Button>
      </span>
    </SettingRow>
  );
}

export function ShortcutsSettings() {
  return (
    <>
      <QuickAskShortcutRow />
      <KeyboardShortcutsList />
    </>
  );
}

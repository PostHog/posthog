import { useServiceOptional } from "@posthog/di/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  formatAccelerator,
  isValidQuickAskAccelerator,
} from "@posthog/shared/quick-ask-shortcuts";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useState } from "react";

const IS_MAC = globalThis.navigator?.platform.startsWith("Mac") ?? false;

const CODE_KEYS: Record<string, string> = {
  Space: "Space",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Backslash: "\\",
  Semicolon: ";",
  Quote: "'",
  BracketLeft: "[",
  BracketRight: "]",
  Minus: "-",
  Equal: "=",
  Backquote: "`",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  Enter: "Return",
  Tab: "Tab",
  Home: "Home",
  End: "End",
  PageUp: "PageUp",
  PageDown: "PageDown",
};

export function acceleratorFromEvent(
  event: KeyboardEvent,
  isMac: boolean,
): string | null {
  let key: string | null = null;
  if (event.code.startsWith("Key")) key = event.code.slice(3);
  else if (event.code.startsWith("Digit")) key = event.code.slice(5);
  else if (/^F\d+$/.test(event.code)) key = event.code;
  else key = CODE_KEYS[event.code] ?? null;
  if (!key) return null;

  const modifiers: string[] = [];
  // Map each physical modifier to its own Electron accelerator. Collapsing
  // Meta and Control into CommandOrControl records a different shortcut than
  // pressed — on macOS a Control+Space would become Command+Space and collide
  // with Spotlight.
  if (event.metaKey) modifiers.push(isMac ? "Command" : "Super");
  if (event.ctrlKey) modifiers.push("Control");
  if (event.altKey) modifiers.push("Alt");
  if (event.shiftKey) modifiers.push("Shift");
  const accelerator = [...modifiers, key].join("+");
  return isValidQuickAskAccelerator(accelerator) ? accelerator : null;
}

function ShortcutRecorder({
  value,
  disabled,
  onRecord,
}: {
  value: string;
  disabled: boolean;
  onRecord: (accelerator: string) => void;
}) {
  const [recording, setRecording] = useState(false);

  useEffect(() => {
    if (!recording) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === "Escape") {
        setRecording(false);
        return;
      }
      const accelerator = acceleratorFromEvent(event, IS_MAC);
      if (accelerator) {
        setRecording(false);
        onRecord(accelerator);
      }
    };
    const cancel = (): void => setRecording(false);
    window.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("blur", cancel);
    };
  }, [recording, onRecord]);

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={disabled}
      onClick={() => setRecording((current) => !current)}
      aria-label="Record shortcut"
      className="min-w-[160px] font-mono"
    >
      {recording
        ? "Press a shortcut… (Esc cancels)"
        : formatAccelerator(value, IS_MAC)}
    </Button>
  );
}

/**
 * Records any modifier+key combination as the panel's global shortcut.
 * Renders nothing on hosts without the panel.
 */
export function QuickAskShortcutSetting({
  disabled = false,
}: {
  disabled?: boolean;
}) {
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

  const handleRecord = (accelerator: string): void => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "quick_ask_shortcut",
      new_value: accelerator,
      old_value: state.shortcut,
    });
    void client.setShortcut(accelerator).then(setState);
  };

  return (
    <SettingsCardRow
      label="Ask PostHog anywhere"
      description={
        state.active && !state.registered
          ? "Another app owns this shortcut; record a different one"
          : "Click, then press the keys you want to summon the panel with"
      }
    >
      <ShortcutRecorder
        value={state.shortcut}
        disabled={disabled}
        onRecord={handleRecord}
      />
    </SettingsCardRow>
  );
}

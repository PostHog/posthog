import { KeyboardShortcutsList } from "@posthog/ui/features/command/KeyboardShortcutsSheet";
import { QuickAskShortcutSetting } from "@posthog/ui/features/settings/sections/QuickAskShortcutSetting";

export function ShortcutsSettings() {
  return (
    <>
      <QuickAskShortcutSetting />
      <KeyboardShortcutsList />
    </>
  );
}

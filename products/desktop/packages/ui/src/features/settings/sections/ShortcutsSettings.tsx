import {
  KeyboardShortcutsList,
  type LeadingShortcutRow,
} from "@posthog/ui/features/command/KeyboardShortcutsSheet";
import { useQuickAskShortcut } from "@posthog/ui/features/quick-ask/useQuickAskShortcut";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";

export function ShortcutsSettings() {
  const quickAsk = useQuickAskShortcut();
  const quickAskRows: LeadingShortcutRow[] = quickAsk
    ? [{ ...quickAsk, onEdit: () => openSettings("quick-ask") }]
    : [];

  return <KeyboardShortcutsList leadingGeneralShortcuts={quickAskRows} />;
}

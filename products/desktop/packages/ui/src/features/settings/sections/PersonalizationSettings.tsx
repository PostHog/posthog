import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import {
  type SyncedCustomInstructions,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { useDebounce } from "@posthog/ui/primitives/hooks/useDebounce";
import { track } from "@posthog/ui/shell/analytics";
import { Callout, Flex, Switch, Text, TextArea } from "@radix-ui/themes";
import { useCallback, useEffect, useState } from "react";

const MAX_INSTRUCTIONS_LENGTH = 2000;

export interface PersonalizationSettingsViewProps {
  instructions: string;
  onInstructionsChange: (value: string) => void;
  onInstructionsBlur: () => void;
  syncFromFile: boolean;
  onSyncToggle: (checked: boolean) => void;
  synced: SyncedCustomInstructions | null;
}

// Pure render of the tab — the container below owns the store wiring,
// debounce and analytics. Storybook targets this.
export function PersonalizationSettingsView({
  instructions,
  onInstructionsChange,
  onInstructionsBlur,
  syncFromFile,
  onSyncToggle,
  synced,
}: PersonalizationSettingsViewProps) {
  return (
    <Flex direction="column">
      <SettingRow
        label="Sync from AGENTS.md / CLAUDE.md"
        description="On start, read your user-level AGENTS.md (or CLAUDE.md if you have no AGENTS.md) and use it instead of the custom instructions below, so they only live in one place"
      >
        <Switch
          checked={syncFromFile}
          onCheckedChange={onSyncToggle}
          size="1"
        />
      </SettingRow>

      <Flex direction="column" gap="1" py="4">
        <Flex direction="column" gap="1" className="mb-2">
          <Text className="font-medium text-sm">Custom instructions</Text>
          <Text color="gray" className="text-[13px]">
            Instructions included in every agent session
          </Text>
        </Flex>

        {syncFromFile && !synced && (
          <Callout.Root size="1" color="amber" mb="2">
            <Callout.Text>
              No AGENTS.md or CLAUDE.md found in ~/.agents, ~/.codex or
              ~/.claude. Nothing is synced — add one of those files, or turn
              sync off to use the instructions below.
            </Callout.Text>
          </Callout.Root>
        )}

        <TextArea
          value={instructions}
          onChange={(e) => onInstructionsChange(e.target.value)}
          onBlur={onInstructionsBlur}
          maxLength={MAX_INSTRUCTIONS_LENGTH}
          placeholder="e.g. Always write tests for new code. Prefer functional patterns."
          rows={6}
          size="1"
          resize="vertical"
          // Radix's disabled state is subtle in dark mode; drop the opacity so
          // the box clearly reads as inactive while the file is in charge.
          className={syncFromFile ? "w-full opacity-50" : "w-full"}
          disabled={syncFromFile}
        />
        {syncFromFile ? (
          synced && (
            <Text color="gray" align="right" className="text-[13px]">
              Using {synced.displayPath}
              {synced.truncated ? " (truncated)" : ""} — edit that file to
              change your personalization
            </Text>
          )
        ) : (
          <Text color="gray" align="right" className="text-[13px]">
            {instructions.length}/{MAX_INSTRUCTIONS_LENGTH}
          </Text>
        )}
      </Flex>
    </Flex>
  );
}

export function PersonalizationSettings() {
  const customInstructions = useSettingsStore((s) => s.customInstructions);
  const setCustomInstructions = useSettingsStore(
    (s) => s.setCustomInstructions,
  );
  const syncFromFile = useSettingsStore(
    (s) => s.syncCustomInstructionsFromFile,
  );
  const setSyncFromFile = useSettingsStore(
    (s) => s.setSyncCustomInstructionsFromFile,
  );
  const synced = useSettingsStore((s) => s.syncedCustomInstructions);

  // The draft renders over the store value only while edits are pending
  // (null = none), instead of copying the store into state and mirroring it
  // back with an effect.
  const [draft, setDraft] = useState<string | null>(null);
  const debouncedDraft = useDebounce(draft, 500);

  const saveInstructions = useCallback(
    (value: string) => {
      const current = useSettingsStore.getState().customInstructions;
      if (value === current) return;
      setCustomInstructions(value);
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "custom_instructions",
        new_value: value.length > 0,
      });
    },
    [setCustomInstructions],
  );

  useEffect(() => {
    if (debouncedDraft === null) return;
    saveInstructions(debouncedDraft);
    // Release the draft once saved so external store changes render again —
    // unless the user typed since this debounce tick.
    setDraft((current) => (current === debouncedDraft ? null : current));
  }, [debouncedDraft, saveInstructions]);

  const handleInstructionsBlur = useCallback(() => {
    if (draft === null) return;
    saveInstructions(draft);
    setDraft(null);
  }, [draft, saveInstructions]);

  const handleSyncToggle = useCallback(
    (checked: boolean) => {
      setSyncFromFile(checked);
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "sync_custom_instructions_from_file",
        new_value: checked,
      });
    },
    [setSyncFromFile],
  );

  return (
    <PersonalizationSettingsView
      instructions={draft ?? customInstructions}
      onInstructionsChange={setDraft}
      onInstructionsBlur={handleInstructionsBlur}
      syncFromFile={syncFromFile}
      onSyncToggle={handleSyncToggle}
      synced={synced}
    />
  );
}

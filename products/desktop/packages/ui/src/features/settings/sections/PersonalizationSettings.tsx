import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { Switch, Textarea } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import {
  type SyncedCustomInstructions,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { useDebounce } from "@posthog/ui/primitives/hooks/useDebounce";
import { track } from "@posthog/ui/shell/analytics";
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

// Pure render of the instructions block. The container below owns the store
// wiring, debounce and analytics. Storybook targets this.
export function PersonalizationSettingsView({
  instructions,
  onInstructionsChange,
  onInstructionsBlur,
  syncFromFile,
  onSyncToggle,
  synced,
}: PersonalizationSettingsViewProps) {
  return (
    <SettingsSection
      label="Custom instructions"
      description="Included in every agent session."
    >
      <SettingsCard>
        <SettingsCardRow
          label="Sync from AGENTS.md / CLAUDE.md"
          description="Use your user-level AGENTS.md (or CLAUDE.md) instead of the instructions below, so they live in one place"
        >
          <Switch
            size="sm"
            checked={syncFromFile}
            onCheckedChange={onSyncToggle}
          />
        </SettingsCardRow>

        <div className="flex flex-col gap-1.5 px-3.5 py-3">
          {syncFromFile && !synced && (
            <div className="rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-2.5 py-2 text-[12px] text-amber-11">
              No AGENTS.md or CLAUDE.md found in your home directory or in
              ~/.agents, ~/.codex or ~/.claude. Nothing is synced. Add one of
              those files, or turn sync off to use the instructions below.
            </div>
          )}

          <Textarea
            value={instructions}
            onChange={(e) => onInstructionsChange(e.target.value)}
            onBlur={onInstructionsBlur}
            maxLength={MAX_INSTRUCTIONS_LENGTH}
            placeholder="e.g. Always write tests for new code. Prefer functional patterns."
            rows={6}
            className={
              syncFromFile
                ? "w-full resize-y text-[12.5px] opacity-50"
                : "w-full resize-y text-[12.5px]"
            }
            disabled={syncFromFile}
          />
          {syncFromFile ? (
            synced && (
              <span className="text-right text-[12px] text-gray-10">
                Using{" "}
                <span className="font-mono text-[11px]">
                  {synced.displayPath}
                </span>
                {synced.truncated ? " (truncated)" : ""}. Edit that file to
                change your personalization.
              </span>
            )
          ) : (
            <span className="text-right text-[12px] text-gray-10 tabular-nums">
              {instructions.length}/{MAX_INSTRUCTIONS_LENGTH}
            </span>
          )}
        </div>
      </SettingsCard>
    </SettingsSection>
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
    <div className="flex flex-col gap-7">
      <PersonalizationSettingsView
        instructions={draft ?? customInstructions}
        onInstructionsChange={setDraft}
        onInstructionsBlur={handleInstructionsBlur}
        syncFromFile={syncFromFile}
        onSyncToggle={handleSyncToggle}
        synced={synced}
      />
      <FunSection />
    </div>
  );
}

function FunSection() {
  const {
    hedgehogMode,
    slotMachineMode,
    brainrotMode,
    setHedgehogMode,
    setSlotMachineMode,
    setBrainrotMode,
  } = useSettingsStore();

  const handleHedgehogModeChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "hedgehog_mode",
        new_value: checked,
        old_value: hedgehogMode,
      });
      setHedgehogMode(checked);
    },
    [hedgehogMode, setHedgehogMode],
  );

  const handleSlotMachineModeChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "slot_machine_mode",
        new_value: checked,
        old_value: slotMachineMode,
      });
      setSlotMachineMode(checked);
    },
    [slotMachineMode, setSlotMachineMode],
  );

  const handleBrainrotModeChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "brainrot_mode",
        new_value: checked,
        old_value: brainrotMode,
      });
      setBrainrotMode(checked);
    },
    [brainrotMode, setBrainrotMode],
  );

  return (
    <SettingsSection label="Fun">
      <SettingsCard>
        <SettingsCardRow
          label="Hedgehog mode"
          description={<HedgehogDescription />}
        >
          <Switch
            size="sm"
            checked={hedgehogMode}
            onCheckedChange={handleHedgehogModeChange}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Slot machine mode 🎰"
          description="A pull-able lever while a task runs. Every run is a gamble."
        >
          <Switch
            size="sm"
            checked={slotMachineMode}
            onCheckedChange={handleSlotMachineModeChange}
          />
        </SettingsCardRow>

        <SettingsCardRow
          label="Brainrot mode ⚡"
          description="Adds a Brainrot option to empty command center cells that fills them with a looping video"
        >
          <Switch
            size="sm"
            checked={brainrotMode}
            onCheckedChange={handleBrainrotModeChange}
          />
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}

function HedgehogDescription() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  const customizeUrl = projectId
    ? buildPostHogUrl(
        `/project/${projectId}/settings/user-customization`,
        cloudRegion,
      )
    : null;

  return (
    <span>
      A hedgehog buddy walks around your screen. It can take a few seconds to
      appear.
      {customizeUrl && (
        <>
          {" "}
          <a
            href={customizeUrl}
            target="_blank"
            rel="noreferrer"
            className="text-accent-11 underline hover:text-accent-12"
          >
            Customize your hedgehog
          </a>
        </>
      )}
    </span>
  );
}

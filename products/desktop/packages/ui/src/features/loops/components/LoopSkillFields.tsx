import { CaretDown } from "@phosphor-icons/react";
import { isUploadableSkillSource } from "@posthog/core/message-editor/skillTags";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  Button as QuillButton,
} from "@posthog/quill";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { TextArea } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import type { LoopFormValues } from "../loopFormTypes";
import type { LoopSkillDraft } from "../loopSkill";
import { Field } from "./LoopFormPrimitives";

const ATTACHED_OPTION_VALUE = "attached-snapshot";

interface PickableSkill {
  name: string;
  source: LoopSkillDraft["source"];
  path: string;
  repoName?: string;
}

/** Same-named skills from different sources must be tellable apart in the picker,
 * or the user can't know which one the loop will snapshot. */
function pickableSkillLabel(
  skill: PickableSkill,
  duplicatedNames: Set<string>,
): string {
  if (!duplicatedNames.has(skill.name)) return skill.name;
  const origin = skill.repoName
    ? `${skill.source}: ${skill.repoName}`
    : skill.source;
  return `${skill.name} (${origin})`;
}

interface SkillOption {
  value: string;
  label: string;
}

/** Searchable skill picker, same quill Combobox shape as the repository picker
 * on the new-task page. Items are the (unique) labels so cmdk's filter matches
 * what the user sees. */
function SkillCombobox({
  options,
  selectedValue,
  disabled,
  onValueChange,
}: {
  options: SkillOption[];
  selectedValue: string;
  disabled: boolean;
  onValueChange: (value: string) => void;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const selectedLabel =
    options.find((option) => option.value === selectedValue)?.label ?? null;

  return (
    <Combobox
      items={options.map((option) => option.label)}
      value={selectedLabel}
      onValueChange={(label) => {
        const picked = options.find((option) => option.label === label);
        if (picked) {
          onValueChange(picked.value);
        }
      }}
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) {
          setSearchQuery("");
        }
      }}
      inputValue={searchQuery}
      onInputValueChange={setSearchQuery}
      disabled={disabled}
    >
      <ComboboxTrigger
        render={
          <QuillButton
            ref={triggerRef}
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-label="Skill"
            className="w-full justify-between"
          >
            <span className="min-w-0 truncate">
              {selectedLabel ?? "Pick a skill…"}
            </span>
            <CaretDown size={10} weight="bold" className="shrink-0" />
          </QuillButton>
        }
      />
      <ComboboxContent
        anchor={triggerRef}
        side="bottom"
        sideOffset={6}
        className="min-w-[280px]"
      >
        <ComboboxInput placeholder="Search skills..." />
        <ComboboxEmpty>No skills found.</ComboboxEmpty>
        <ComboboxList>
          {(label: string) => (
            <ComboboxItem key={label} value={label}>
              {label}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

export function LoopInstructionsFields({
  values,
  disabled,
  onPatch,
}: {
  values: LoopFormValues;
  disabled: boolean;
  onPatch: (next: Partial<LoopFormValues>) => void;
}) {
  const { localWorkspaces } = useHostCapabilities();
  const trpc = useHostTRPC();
  const lastSkill = useRef<LoopSkillDraft | null>(values.skill);
  const { data: localSkillData } = useQuery({
    ...trpc.skills.list.queryOptions(),
    enabled: localWorkspaces,
  });
  const localSkills: PickableSkill[] = (localSkillData ?? []).flatMap(
    (skill) =>
      isUploadableSkillSource(skill.source)
        ? [
            {
              name: skill.name,
              source: skill.source,
              path: skill.path,
              repoName: skill.repoName,
            },
          ]
        : [],
  );
  const nameCounts = new Map<string, number>();
  for (const skill of localSkills) {
    nameCounts.set(skill.name, (nameCounts.get(skill.name) ?? 0) + 1);
  }
  const duplicatedNames = new Set(
    [...nameCounts].flatMap(([name, count]) => (count > 1 ? [name] : [])),
  );

  const skill = values.skill;
  const skillUnavailableHint = localWorkspaces
    ? "No local skills found. Create one under Settings → Skills first."
    : "Picking a skill needs the desktop app, where your local skills live.";

  const selectedValue =
    skill?.kind === "local" ? skill.path : skill ? ATTACHED_OPTION_VALUE : "";
  const skillOptions = [
    ...(skill?.kind === "attached" &&
    !localSkills.some((local) => local.name === skill.name)
      ? [
          {
            value: ATTACHED_OPTION_VALUE,
            label: `${skill.name} (attached snapshot)`,
          },
        ]
      : []),
    ...localSkills.map((local) => ({
      value: local.path,
      label:
        skill?.kind === "attached" && local.name === skill.name
          ? `${pickableSkillLabel(local, duplicatedNames)} (pick again to refresh the snapshot)`
          : pickableSkillLabel(local, duplicatedNames),
    })),
  ];

  const handleModeChange = (mode: string) => {
    if (mode === "skill") {
      // Restore whatever was picked before the toggle away; defaulting to the
      // first local skill would silently swap the loop onto an unrelated one.
      const restored =
        lastSkill.current ??
        (localSkills[0] ? { kind: "local" as const, ...localSkills[0] } : null);
      if (!restored) return;
      onPatch({ skill: restored });
    } else {
      if (skill) {
        lastSkill.current = skill;
      }
      onPatch({ skill: null });
    }
  };

  const handleSkillChange = (value: string) => {
    if (value === ATTACHED_OPTION_VALUE) return;
    const picked = localSkills.find((local) => local.path === value);
    if (picked) {
      const draft: LoopSkillDraft = { kind: "local", ...picked };
      lastSkill.current = draft;
      onPatch({ skill: draft });
    }
  };

  return (
    <>
      <Field label="Prompt source" required>
        <SettingsOptionSelect
          ariaLabel="Prompt source"
          value={skill ? "skill" : "instructions"}
          disabled={disabled}
          options={[
            { value: "instructions", label: "Write instructions" },
            { value: "skill", label: "Run a skill" },
          ]}
          onValueChange={handleModeChange}
        />
        {!skill && localSkills.length === 0 ? (
          <span className="text-[11px] text-gray-10 leading-snug">
            {skillUnavailableHint}
          </span>
        ) : null}
      </Field>

      {skill ? (
        <>
          <Field
            label="Skill"
            required
            hint="The skill is snapshotted when you save; every run installs that snapshot into its sandbox."
          >
            <SkillCombobox
              options={skillOptions}
              selectedValue={selectedValue}
              disabled={disabled}
              onValueChange={handleSkillChange}
            />
          </Field>
          <Field
            label="Additional context"
            hint="Optional extra instructions appended after the skill invocation on every run."
          >
            <TextArea
              value={values.skillContext}
              placeholder="Only check the release workflow and post the summary to #eng-standup."
              disabled={disabled}
              className="min-h-[120px] text-[13px] leading-relaxed"
              onChange={(e) => onPatch({ skillContext: e.target.value })}
            />
          </Field>
        </>
      ) : (
        <Field label="Instructions" required>
          <TextArea
            value={values.instructions}
            placeholder="Summarize failing CI runs from the last 24 hours and post the summary to #eng-standup."
            disabled={disabled}
            className="min-h-[220px] text-[13px] leading-relaxed"
            onChange={(e) => onPatch({ instructions: e.target.value })}
          />
        </Field>
      )}
    </>
  );
}

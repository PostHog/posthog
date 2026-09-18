import { CaretDown, X } from "@phosphor-icons/react";
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
import { useTeamSkills } from "@posthog/ui/features/skills/useTeamSkills";
import { useRef, useState } from "react";
import { Field } from "./LoopFormPrimitives";

/** The "Create AI task" step accepts at most this many skills. */
export const MAX_LOOP_TEAM_SKILLS = 10;

/**
 * Picks the team skills a workflow-backed loop attaches to each run. Skills
 * come from the team's skills store by name, so the agent always reads the
 * current version and nothing is uploaded from this machine.
 */
export function LoopTeamSkillsFields({
  value,
  disabled,
  onChange,
}: {
  value: string[];
  disabled: boolean;
  onChange: (names: string[]) => void;
}) {
  const { data: listing, isLoading, isError } = useTeamSkills([]);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const available = listing?.available ?? false;
  const options = (listing?.skills ?? [])
    .map((skill) => skill.name)
    .filter((name) => !value.includes(name));
  const atCap = value.length >= MAX_LOOP_TEAM_SKILLS;

  let hint: string;
  if (isLoading) {
    hint = "Loading team skills…";
  } else if (isError) {
    hint = "Couldn't load team skills. Reopen the form to try again.";
  } else if (!available) {
    hint = "Team skills aren't enabled for this organization.";
  } else if (atCap) {
    hint = `A loop can attach up to ${MAX_LOOP_TEAM_SKILLS} skills.`;
  } else {
    hint =
      "Optional. The agent reads the current version of each skill at the start of every run.";
  }

  const pickerDisabled =
    disabled || isLoading || isError || !available || atCap;

  return (
    <Field label="Skills" hint={hint}>
      <div className="flex flex-col gap-2">
        {value.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {value.map((name) => (
              <span
                key={name}
                className="flex items-center gap-1 rounded-(--radius-2) border border-border bg-(--gray-2) py-0.5 pr-1 pl-2 text-[12px] text-gray-12"
              >
                {name}
                <QuillButton
                  variant="link-muted"
                  size="icon-xs"
                  disabled={disabled}
                  aria-label={`Remove ${name}`}
                  onClick={() =>
                    onChange(value.filter((selected) => selected !== name))
                  }
                >
                  <X size={10} weight="bold" />
                </QuillButton>
              </span>
            ))}
          </div>
        ) : null}
        <Combobox
          items={options}
          value={null}
          onValueChange={(name) => {
            if (typeof name === "string" && name && !atCap) {
              onChange([...value, name]);
            }
          }}
          open={open}
          onOpenChange={(nextOpen) => {
            setOpen(nextOpen);
            if (!nextOpen) setSearchQuery("");
          }}
          inputValue={searchQuery}
          onInputValueChange={setSearchQuery}
          disabled={pickerDisabled}
        >
          <ComboboxTrigger
            render={
              <QuillButton
                ref={triggerRef}
                variant="outline"
                size="sm"
                disabled={pickerDisabled}
                aria-label="Add a skill"
                className="w-full max-w-[360px] justify-between"
              >
                <span className="min-w-0 truncate">Add a skill…</span>
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
            <ComboboxInput placeholder="Search team skills..." />
            <ComboboxEmpty>No skills found.</ComboboxEmpty>
            <ComboboxList>
              {(name: string) => (
                <ComboboxItem key={name} value={name}>
                  {name}
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      </div>
    </Field>
  );
}

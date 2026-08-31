import { Text, ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import { TextArea } from "@radix-ui/themes";
import { useTeamSkills } from "../../skills/useTeamSkills";
import type { LoopFormValues } from "../loopFormTypes";
import { Field } from "./LoopFormPrimitives";

/**
 * hog_flows-backed replacement for `LoopInstructionsFields`: plain instructions text plus a
 * multi-select of the team's skills store (see `useTeamSkills`), matching the create-task
 * action's `skills` input — a list of names, not the single uploaded-bundle skill the Loops API
 * models. No local/repo/marketplace skill sources here; those only exist for Loop-backed forms.
 */
export function LoopTeamSkillsFields({
  values,
  disabled,
  onPatch,
}: {
  values: LoopFormValues;
  disabled: boolean;
  onPatch: (next: Partial<LoopFormValues>) => void;
}) {
  const { data, isLoading } = useTeamSkills([]);
  const skillNames = data?.skills.map((skill) => skill.name) ?? [];
  // A previously-attached skill that's since been archived still needs to render, so it can be
  // seen and removed.
  const options = [...new Set([...skillNames, ...values.skillNames])];

  return (
    <div className="flex flex-col gap-3">
      <Field label="Instructions">
        <TextArea
          value={values.instructions}
          placeholder="What should the agent do?"
          disabled={disabled}
          rows={6}
          className="text-[13px] leading-relaxed"
          onChange={(e) => onPatch({ instructions: e.target.value })}
        />
      </Field>
      <Field label="Skills">
        {isLoading ? (
          <Text className="text-[12px] text-gray-10">Loading skills…</Text>
        ) : options.length === 0 ? (
          <Text className="text-[12px] text-gray-10">No team skills yet.</Text>
        ) : (
          <ToggleGroup
            multiple
            disabled={disabled}
            value={values.skillNames}
            onValueChange={(skillNames: string[]) => onPatch({ skillNames })}
            className="flex flex-wrap gap-1.5"
          >
            {options.map((name) => (
              <ToggleGroupItem
                key={name}
                value={name}
                size="sm"
                variant="outline"
              >
                {name}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </Field>
    </div>
  );
}

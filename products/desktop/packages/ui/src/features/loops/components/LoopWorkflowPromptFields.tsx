import { Textarea } from "@posthog/quill";
import type { LoopFormValues } from "../loopFormTypes";
import { Field } from "./LoopFormPrimitives";
import { LoopTeamSkillsFields } from "./LoopTeamSkillsFields";

/**
 * The prompt of a workflow-backed loop: free-form instructions plus team
 * skills. There is no local-skill mode here, because the workflow reads skills
 * from the team store at run time instead of a snapshot uploaded from a laptop.
 */
export function LoopWorkflowPromptFields({
  values,
  disabled,
  onPatch,
}: {
  values: LoopFormValues;
  disabled: boolean;
  onPatch: (next: Partial<LoopFormValues>) => void;
}) {
  return (
    <>
      <Field label="Instructions" required>
        <Textarea
          value={values.instructions}
          placeholder="Summarize failing CI runs from the last 24 hours and post the summary to #eng-standup."
          disabled={disabled}
          className="min-h-[220px] text-[13px] leading-relaxed"
          onChange={(e) => onPatch({ instructions: e.target.value })}
        />
      </Field>
      <LoopTeamSkillsFields
        value={values.teamSkills}
        disabled={disabled}
        onChange={(teamSkills) => onPatch({ teamSkills })}
      />
    </>
  );
}

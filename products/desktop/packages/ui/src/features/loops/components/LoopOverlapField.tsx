import type { LoopSchemas } from "@posthog/api-client/loops";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { Field } from "./LoopFormPrimitives";

const OVERLAP_OPTIONS: {
  value: LoopSchemas.LoopOverlapPolicyEnum;
  label: string;
}[] = [
  { value: "skip", label: "Skip the new run" },
  { value: "allow", label: "Run in parallel" },
  { value: "cancel_previous", label: "Cancel the previous run" },
];

interface LoopOverlapFieldProps {
  overlapPolicy: LoopSchemas.LoopOverlapPolicyEnum;
  onChange: (policy: LoopSchemas.LoopOverlapPolicyEnum) => void;
  disabled?: boolean;
}

export function LoopOverlapField({
  overlapPolicy,
  onChange,
  disabled,
}: LoopOverlapFieldProps) {
  return (
    <Field
      label="Overlapping runs"
      hint="What happens when this loop is triggered while a run is still going."
    >
      <SettingsOptionSelect
        value={overlapPolicy}
        options={OVERLAP_OPTIONS}
        onValueChange={(value) =>
          onChange(value as LoopSchemas.LoopOverlapPolicyEnum)
        }
        disabled={disabled}
        size="lg"
        ariaLabel="Overlapping runs"
      />
    </Field>
  );
}

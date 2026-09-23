import type { SpaceSetupDraft } from "@posthog/core/canvas/spaceSetup";
import {
  Field,
  FieldDescription,
  FieldLabel,
  Input,
  Textarea,
} from "@posthog/quill";

export function SpaceFeatureFields({
  value,
  disabled,
  onChange,
}: {
  value: SpaceSetupDraft["feature"];
  disabled?: boolean;
  onChange: (value: SpaceSetupDraft["feature"]) => void;
}) {
  return (
    <>
      <Field>
        <FieldLabel htmlFor="space-feature-name">Feature</FieldLabel>
        <Input
          id="space-feature-name"
          autoFocus
          value={value.name}
          disabled={disabled}
          placeholder="e.g. Onboarding checklist"
          onChange={(event) => onChange({ ...value, name: event.target.value })}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor="space-feature-flag">Feature flag key</FieldLabel>
        <Input
          id="space-feature-flag"
          value={value.flagKey}
          disabled={disabled}
          placeholder="e.g. onboarding-checklist"
          onChange={(event) =>
            onChange({ ...value, flagKey: event.target.value })
          }
        />
        <FieldDescription>
          Optional. Leave it empty and the setup task proposes a key.
        </FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="space-feature-description">
          What it does
        </FieldLabel>
        <Textarea
          id="space-feature-description"
          rows={3}
          className="text-xs leading-4"
          value={value.description}
          disabled={disabled}
          placeholder="One or two sentences. Optional."
          onChange={(event) =>
            onChange({ ...value, description: event.target.value })
          }
        />
      </Field>
    </>
  );
}

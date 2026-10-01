import type { SpaceSetupDraft } from "@posthog/core/canvas/spaceSetup";
import {
  Field,
  FieldDescription,
  FieldLabel,
  Input,
  Text,
  Textarea,
} from "@posthog/quill";
import type {
  SpaceGoalDirection,
  SpaceGoalPeriod,
} from "@posthog/shared/domain-types";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";

const DIRECTIONS: { value: SpaceGoalDirection; label: string }[] = [
  { value: "at_least", label: "At least" },
  { value: "at_most", label: "At most" },
];

const PERIODS: { value: SpaceGoalPeriod; label: string }[] = [
  { value: "day", label: "Per day" },
  { value: "week", label: "Per week" },
  { value: "month", label: "Per month" },
];

export function SpaceGoalFields({
  value,
  disabled,
  onChange,
}: {
  value: SpaceSetupDraft["goal"];
  disabled?: boolean;
  onChange: (value: SpaceSetupDraft["goal"]) => void;
}) {
  return (
    <>
      <Field>
        <FieldLabel htmlFor="space-goal-statement">Goal</FieldLabel>
        <Textarea
          id="space-goal-statement"
          autoFocus
          rows={3}
          className="text-xs leading-4"
          value={value.statement}
          disabled={disabled}
          placeholder="e.g. Increase the weekly activation rate of new desktop users"
          onChange={(event) =>
            onChange({ ...value, statement: event.target.value })
          }
        />
        <FieldDescription>
          Name the metric in plain words. The setup task finds or writes the
          measure and records a baseline.
        </FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="space-goal-target">Target</FieldLabel>
        <div className="flex flex-wrap items-center gap-2">
          <SettingsSegmented
            value={value.direction}
            options={DIRECTIONS}
            disabled={disabled}
            ariaLabel="Target direction"
            onValueChange={(direction) =>
              onChange({ ...value, direction: direction as SpaceGoalDirection })
            }
          />
          <Input
            id="space-goal-target"
            inputMode="decimal"
            className="w-28 tabular-nums"
            value={value.target}
            disabled={disabled}
            placeholder="20%"
            onChange={(event) =>
              onChange({ ...value, target: event.target.value })
            }
          />
          <SettingsSegmented
            value={value.period}
            options={PERIODS}
            disabled={disabled}
            ariaLabel="Measurement period"
            onValueChange={(period) =>
              onChange({ ...value, period: period as SpaceGoalPeriod })
            }
          />
        </div>
        <FieldDescription>
          Optional. Leave the target empty to let the setup task propose one
          from the baseline.
        </FieldDescription>
      </Field>
      <Field>
        <FieldLabel htmlFor="space-goal-deadline">Deadline</FieldLabel>
        <div className="flex items-center gap-2">
          <Input
            id="space-goal-deadline"
            type="date"
            className="w-40"
            value={value.deadline}
            disabled={disabled}
            onChange={(event) =>
              onChange({ ...value, deadline: event.target.value })
            }
          />
          <Text size="xs" variant="muted">
            Optional
          </Text>
        </div>
      </Field>
    </>
  );
}

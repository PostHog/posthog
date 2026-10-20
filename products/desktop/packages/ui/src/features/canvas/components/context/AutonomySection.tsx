import type { AutonomyLevel } from "@posthog/core/canvas/contextDocument";
import { Text } from "@posthog/quill";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";
import { SectionHeader } from "./SectionHeader";

const LEVELS: { value: AutonomyLevel; label: string; description: string }[] = [
  {
    value: "propose",
    label: "Propose",
    description:
      "Loops measure the goal, rank ideas, and recommend the next change. They open nothing.",
  },
  {
    value: "ship_drafts",
    label: "Ship drafts",
    description:
      "Loops also open draft pull requests and draft experiments for you to review. They never change a live flag.",
  },
  {
    value: "autopilot",
    label: "Autopilot",
    description:
      "Loops also release a winning experiment variant and open its cleanup pull request when the decision rule is met.",
  },
];

export function AutonomySection({
  value,
  disabled,
  onChange,
}: {
  value: AutonomyLevel;
  disabled?: boolean;
  onChange: (level: AutonomyLevel) => void;
}) {
  const current = LEVELS.find((level) => level.value === value) ?? LEVELS[0];
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader label="Autonomy" />
      <div className="flex flex-col gap-2">
        <SettingsSegmented
          value={value}
          options={LEVELS}
          disabled={disabled}
          ariaLabel="Autonomy level"
          onValueChange={(level) => onChange(level as AutonomyLevel)}
        />
        <Text size="xs" variant="muted">
          {current.description} Loops read the level on their next run.
        </Text>
      </div>
    </section>
  );
}

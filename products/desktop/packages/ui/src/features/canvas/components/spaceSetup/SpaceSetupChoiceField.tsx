import type { SpaceSetupChoice } from "@posthog/core/canvas/spaceSetup";
import {
  type RadioCardOption,
  RadioCards,
} from "@posthog/ui/primitives/RadioCards";

const OPTIONS: readonly RadioCardOption<SpaceSetupChoice>[] = [
  {
    value: "none",
    title: "Nothing yet",
    description:
      "Keep related work and context together. You can add a goal later.",
  },
  {
    value: "goal",
    title: "A goal",
    description:
      "Move one metric. Loops measure it and recommend changes. Let them open pull requests and experiments from the context page when you are ready.",
  },
  {
    value: "feature",
    title: "A feature",
    description:
      "Ship one feature behind a flag. The context page tracks adoption, the flag, and related errors.",
  },
];

export function SpaceSetupChoiceField({
  value,
  disabled,
  onChange,
}: {
  value: SpaceSetupChoice;
  disabled?: boolean;
  onChange: (value: SpaceSetupChoice) => void;
}) {
  return (
    <RadioCards
      value={value}
      options={
        disabled ? OPTIONS.map((option) => ({ ...option, disabled })) : OPTIONS
      }
      onChange={onChange}
      ariaLabel="What is this space for?"
      dataAttrPrefix="space-setup-choice"
    />
  );
}

import { Lightbulb } from "@phosphor-icons/react";

/**
 * A skill's mark. One icon for every skill, matching the Skills page's own:
 * the project owners' avatars are photographs of people, which read as
 * something else entirely in a list of settings.
 */
export function LeanSkillMark({ size = 20 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size }}
      className="flex shrink-0 items-center justify-center rounded-(--radius-2) bg-(--gray-3) text-(--gray-11)"
    >
      <Lightbulb size={Math.round(size * 0.62)} />
    </span>
  );
}

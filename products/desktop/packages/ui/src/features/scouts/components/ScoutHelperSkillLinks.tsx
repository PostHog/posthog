import type { ScoutSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useSkillsSelectionActions } from "@posthog/ui/features/skills/skillsSelectionStore";
import { track } from "@posthog/ui/shell/analytics";
import { Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";

// The two official scout helper skills are bundled with the PostHog plugin, so
// they open in the in-app Skills view rather than linking out to GitHub. `name`
// is the skill's frontmatter name, used to select it once Skills loads.
const HELPER_SKILLS = [
  { label: "writing agents", name: "authoring-scouts" },
  { label: "exploring agents", name: "exploring-scouts" },
];

/** One-line pointer to the two official scout helper skills, opened in-app. */
export function ScoutHelperSkillLinks({ surface }: { surface: ScoutSurface }) {
  const { requestSkill } = useSkillsSelectionActions();
  return (
    <Text className="text-[12px] text-gray-10">
      Skills:{" "}
      {HELPER_SKILLS.map((skill, index) => (
        <span key={skill.name}>
          {index > 0 ? " · " : null}
          <Link
            to="/settings/$category"
            params={{ category: "skills" }}
            onClick={() => {
              track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                action_type: "open_helper_skill",
                surface,
                helper_skill: skill.label,
              });
              requestSkill(skill.name);
            }}
            className="text-accent-11 no-underline hover:text-accent-12"
          >
            {skill.label}
          </Link>
        </span>
      ))}
    </Text>
  );
}

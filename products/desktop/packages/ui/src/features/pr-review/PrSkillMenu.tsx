import { CaretDownIcon, SparkleIcon } from "@phosphor-icons/react";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { useTeamSkills } from "@posthog/ui/features/skills/useTeamSkills";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";

export function PrSkillMenu({ prUrl }: { prUrl: string }) {
  const { data: listing, isLoading, isError } = useTeamSkills([]);
  const pr = parsePrUrl(prUrl);
  if (!pr) return null;

  const skills = [...(listing?.skills ?? [])].sort(
    (first, second) =>
      Number(second.name === "pr-shepherd") -
        Number(first.name === "pr-shepherd") ||
      first.name.localeCompare(second.name),
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            className="h-9 gap-2 px-4 text-[13px]"
            data-attr="pr-run-store-skill"
          >
            <SparkleIcon size={15} />
            Run skill
            <CaretDownIcon size={13} />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="max-h-64 min-w-52 overflow-y-auto"
      >
        {skills.length ? (
          skills.map((skill) => (
            <DropdownMenuItem
              key={skill.id}
              onClick={() =>
                openTaskInput({
                  initialPrompt: `Run the ${skill.name} skill from the PostHog skills store for this pull request: ${prUrl}`,
                  initialCloudRepository: pr.repoSlug,
                })
              }
            >
              {skill.name}
            </DropdownMenuItem>
          ))
        ) : (
          <DropdownMenuItem disabled>
            {isLoading
              ? "Loading team skills…"
              : isError
                ? "Couldn't load team skills"
                : "No team skills available"}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

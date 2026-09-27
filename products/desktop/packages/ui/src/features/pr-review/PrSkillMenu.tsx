import { CaretDownIcon, SparkleIcon } from "@phosphor-icons/react";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useTeamSkills } from "@posthog/ui/features/skills/useTeamSkills";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { Link } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { usePrSkillUsageStore } from "./prSkillUsageStore";

export function PrSkillMenu({ prUrl }: { prUrl: string }) {
  const { data: listing, isLoading, isError } = useTeamSkills([]);
  const client = useOptionalAuthenticatedClient();
  const identity = useAuthStateValue(getAuthIdentity);
  const { data: user } = useCurrentUser({ client });
  const scope =
    identity && user?.uuid ? JSON.stringify([identity, user.uuid]) : null;
  const counts = usePrSkillUsageStore((state) =>
    scope ? state.countsByScope[scope] : undefined,
  );
  const recordChoice = usePrSkillUsageStore((state) => state.recordChoice);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const pr = parsePrUrl(prUrl);
  if (!pr) return null;

  const skills = (
    listing
      ? listing.skills.map((skill) => skill.name)
      : Object.keys(counts ?? {})
  ).sort(
    (first, second) =>
      (counts?.[second] ?? 0) - (counts?.[first] ?? 0) ||
      first.localeCompare(second),
  );

  const handleSelect = (name: string | null) => {
    if (!name) return;
    if (scope) recordChoice(scope, name);
    openTaskInput({
      initialPrompt: `Run the ${name} skill from the PostHog skills store for this pull request: ${prUrl}`,
      initialCloudRepository: pr.repoSlug,
    });
    setOpen(false);
  };

  return (
    <Combobox
      items={skills}
      value={null}
      onValueChange={handleSelect}
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setSearchQuery("");
      }}
      inputValue={searchQuery}
      onInputValueChange={setSearchQuery}
    >
      <ComboboxTrigger
        render={
          <Button
            ref={triggerRef}
            type="button"
            variant="outline"
            aria-label="Run skill"
            className="h-9 gap-2 px-4 text-[13px]"
            data-attr="pr-run-store-skill"
          >
            <SparkleIcon size={15} />
            Run skill
            <CaretDownIcon size={13} />
          </Button>
        }
      />
      <ComboboxContent
        anchor={triggerRef}
        side="bottom"
        sideOffset={6}
        className="min-w-64"
      >
        <ComboboxInput placeholder="Search team skills…" />
        <ComboboxEmpty>
          {isLoading ? (
            "Loading team skills…"
          ) : isError ? (
            "Couldn't load team skills"
          ) : listing?.skills.length === 0 ? (
            <span>
              No team skills yet.{" "}
              <Link
                to="/settings/$category"
                params={{ category: "skills" }}
                className="underline"
              >
                Explore the skills store
              </Link>
            </span>
          ) : (
            "No matching skills"
          )}
        </ComboboxEmpty>
        <ComboboxList className="max-h-64 overflow-y-auto">
          {(name: string) => (
            <ComboboxItem key={name} value={name}>
              {name}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

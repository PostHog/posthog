import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { SettingsSection } from "@posthog/ui/features/settings/components/SettingsCard";
import { PersonalGithubInstallationsSection } from "@posthog/ui/features/settings/sections/PersonalGithubInstallationsSection";
import { ProjectGithubConnectionSection } from "@posthog/ui/features/settings/sections/ProjectGithubConnectionSection";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";

const GITHUB_DOCS_URL = "https://posthog.com/docs/libraries/github";

export function GitHubSettings() {
  return (
    <div className="flex flex-col gap-6">
      <SettingsSection label="Project connection">
        <ProjectGithubConnectionSection />
      </SettingsSection>
      <SettingsSection label="Your GitHub account">
        <PersonalGithubInstallationsSection />
      </SettingsSection>
      <button
        type="button"
        onClick={() => void openUrlInBrowser(GITHUB_DOCS_URL)}
        className="inline-flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-(--accent-11) text-xs no-underline hover:text-(--accent-12)"
      >
        Learn about the GitHub integration
        <ArrowSquareOutIcon size={11} />
      </button>
    </div>
  );
}

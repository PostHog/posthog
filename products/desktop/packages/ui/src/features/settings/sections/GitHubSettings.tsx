import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { PersonalGithubInstallationsSection } from "@posthog/ui/features/settings/sections/PersonalGithubInstallationsSection";
import { ProjectGithubConnectionSection } from "@posthog/ui/features/settings/sections/ProjectGithubConnectionSection";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";

const GITHUB_DOCS_URL = "https://posthog.com/docs/libraries/github";

export function GitHubSettings() {
  return (
    <div className="flex flex-col gap-7">
      <ProjectGithubConnectionSection />
      <PersonalGithubInstallationsSection />
      <button
        type="button"
        onClick={() => void openUrlInBrowser(GITHUB_DOCS_URL)}
        className="inline-flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-gray-10 text-xs no-underline hover:text-gray-12"
      >
        Learn about the GitHub integration
        <ArrowSquareOutIcon size={11} />
      </button>
    </div>
  );
}

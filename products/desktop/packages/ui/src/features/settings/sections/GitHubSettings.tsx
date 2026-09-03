import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { GITHUB_CODE_CONTEXT_MESSAGE } from "@posthog/core/integrations/connectErrors";
import { Button } from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { PersonalGithubInstallationsSection } from "@posthog/ui/features/settings/sections/PersonalGithubInstallationsSection";
import { ProjectGithubConnectionSection } from "@posthog/ui/features/settings/sections/ProjectGithubConnectionSection";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { getPostHogUrl } from "@posthog/ui/utils/urls";

const GITHUB_DOCS_URL = "https://posthog.com/docs/libraries/github?tab=Desktop";

export function GitHubSettings() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);

  const githubSettingsUrl = projectId
    ? getPostHogUrl(
        `/project/${projectId}/settings/project-integrations#integration-github`,
        cloudRegion,
      )
    : null;

  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-col gap-1 rounded-(--radius-3) border border-border bg-card px-3.5 py-3">
        <p className="m-0 font-medium text-[13px] text-foreground">
          Why connect GitHub?
        </p>
        <p className="m-0 text-[12px] text-muted-foreground leading-snug">
          {GITHUB_CODE_CONTEXT_MESSAGE} Your personal connection lets agents
          open pull requests and comments as you.
        </p>
      </div>
      <ProjectGithubConnectionSection />
      <PersonalGithubInstallationsSection />
      <div className="flex flex-wrap items-center gap-3">
        {githubSettingsUrl ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void openUrlInBrowser(githubSettingsUrl)}
          >
            <ArrowSquareOutIcon size={12} />
            Advanced settings in PostHog
          </Button>
        ) : null}
        <button
          type="button"
          onClick={() => void openUrlInBrowser(GITHUB_DOCS_URL)}
          className="ml-auto inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-muted-foreground text-xs no-underline hover:text-foreground"
        >
          Learn about the GitHub integration
          <ArrowSquareOutIcon size={11} />
        </button>
      </div>
    </div>
  );
}

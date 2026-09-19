import { Switch } from "@posthog/quill";
import { useSignalUserAutonomyConfig } from "@posthog/ui/features/inbox/hooks/useSignalUserAutonomyConfig";
import { useSignalUserAutonomyMutations } from "@posthog/ui/features/inbox/hooks/useSignalUserAutonomyMutations";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";

/**
 * Per-user opt-in to being added as a GitHub assignee on the implementation pull request for
 * reports that suggest this user as reviewer. Off by default, because the assignment is visible
 * to everybody on the pull request.
 */
export function SignalGithubAssignmentSettings() {
  const { data: config, isLoading } = useSignalUserAutonomyConfig();
  const { handleUpdateGithubAssignment, isUpdatingGithubAssignment } =
    useSignalUserAutonomyMutations();

  return (
    <SettingsCard>
      <SettingsCardRow
        label="Assign me on GitHub"
        description="Adds you as an assignee on pull requests for reports that suggest you as reviewer, in all your projects"
      >
        {isLoading ? (
          <div className="h-[20px] w-[36px] animate-pulse rounded-full bg-gray-3" />
        ) : (
          <Switch
            size="sm"
            checked={config?.github_assign_on_pull_request ?? false}
            onCheckedChange={(next) => handleUpdateGithubAssignment(next)}
            disabled={isUpdatingGithubAssignment}
            aria-label="Assign me on GitHub pull requests"
          />
        )}
      </SettingsCardRow>
    </SettingsCard>
  );
}

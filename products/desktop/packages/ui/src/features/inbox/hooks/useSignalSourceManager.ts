import { useSignalEvaluations } from "@posthog/ui/features/inbox/hooks/useSignalEvaluations";
import { useSignalSourceToggles } from "@posthog/ui/features/inbox/hooks/useSignalSourceToggles";
import { useSignalTeamConfig } from "@posthog/ui/features/inbox/hooks/useSignalTeamConfig";
import { useSignalTeamConfigMutations } from "@posthog/ui/features/inbox/hooks/useSignalTeamConfigMutations";
import { useSignalUserAutonomyConfig } from "@posthog/ui/features/inbox/hooks/useSignalUserAutonomyConfig";
import { useSignalUserAutonomyMutations } from "@posthog/ui/features/inbox/hooks/useSignalUserAutonomyMutations";

/**
 * Aggregator over the focused source/evaluations/team-config/autonomy hooks.
 * Prefer the focused hook for the concern you need; this entry point exists
 * so call sites that touch many concerns at once can destructure flat.
 */
export function useSignalSourceManager() {
  const toggles = useSignalSourceToggles();
  const evaluations = useSignalEvaluations();
  const { data: teamConfig, isLoading: teamConfigLoading } =
    useSignalTeamConfig();
  const teamMutations = useSignalTeamConfigMutations();
  const { data: userAutonomyConfig, isLoading: userAutonomyConfigLoading } =
    useSignalUserAutonomyConfig();
  const userAutonomyMutations = useSignalUserAutonomyMutations();

  return {
    // Source toggles
    displayValues: toggles.displayValues,
    sourceStates: toggles.sourceStates,
    setupSource: toggles.setupSource,
    isLoading: toggles.isLoading,
    handleToggle: toggles.handleToggle,
    handleSetup: toggles.handleSetup,
    handleSetupComplete: toggles.handleSetupComplete,
    handleSetupCancel: toggles.handleSetupCancel,

    // Evaluations
    evaluations: evaluations.evaluations,
    evaluationsUrl: evaluations.evaluationsUrl,
    handleToggleEvaluation: evaluations.handleToggleEvaluation,

    // Team config
    teamConfig,
    teamConfigLoading,
    handleUpdateAutostartPriority: teamMutations.handleUpdateAutostartPriority,
    handleUpdateTeamSlackChannel: teamMutations.handleUpdateTeamSlackChannel,
    handleUpdateAutostartBaseBranches:
      teamMutations.handleUpdateAutostartBaseBranches,

    // User autonomy
    userAutonomyConfig,
    userAutonomyConfigLoading,
    handleUpdateSlackNotifications:
      userAutonomyMutations.handleUpdateSlackNotifications,
  };
}

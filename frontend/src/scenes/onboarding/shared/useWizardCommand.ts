import { useValues } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Region } from '~/types'

const BASE_COMMAND = 'npx -y @posthog/wizard@latest'

export interface UseWizardCommandOptions {
    /**
     * Append `--project-id=<current team>` so the wizard pre-targets the project
     * being viewed (and, once the consent screen honors the hint, pre-selects it).
     * Harmless if the user authorizes the same project.
     */
    pinProjectId?: boolean
}

/**
 * The canonical `npx @posthog/wizard` command for this region, with an optional
 * subcommand (e.g. `mcp-analytics`). Kept dependency-light so eagerly-loaded
 * surfaces (like the product empty-state gate) can use it without pulling in
 * heavy onboarding components.
 */
export function useWizardCommand(
    subcommand?: string,
    { pinProjectId = false }: UseWizardCommandOptions = {}
): { wizardCommand: string; isCloudOrDev: boolean } {
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)

    const region = preflight?.region || Region.US
    const subcommandPart = subcommand ? ` ${subcommand}` : ''
    const regionPart = region === Region.EU ? ' --region eu' : ''
    const projectPart = pinProjectId && currentTeam?.id ? ` --project-id=${currentTeam.id}` : ''

    return {
        wizardCommand: `${BASE_COMMAND}${subcommandPart}${regionPart}${projectPart}`,
        isCloudOrDev: isCloudOrDev ?? false,
    }
}

import { useValues } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

const BASE_COMMAND = 'npx -y @posthog/wizard@latest'

/**
 * The canonical `npx @posthog/wizard` command for this region, with an optional
 * subcommand (e.g. `mcp-analytics`). Kept dependency-light so eagerly-loaded
 * surfaces (like the product empty-state gate) can use it without pulling in
 * heavy onboarding components.
 */
export function useWizardCommand(subcommand?: string): { wizardCommand: string; isCloudOrDev: boolean } {
    const { preflight, isCloudOrDev } = useValues(preflightLogic)

    const region = preflight?.region || Region.US
    const subcommandPart = subcommand ? ` ${subcommand}` : ''

    return {
        wizardCommand: `${BASE_COMMAND}${subcommandPart}${region === Region.EU ? ' --region eu' : ''}`,
        isCloudOrDev: isCloudOrDev ?? false,
    }
}

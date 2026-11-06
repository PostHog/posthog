import { IconGitLab, IconGithub } from '@posthog/icons'

import depotLogo from 'public/services/depot.png'

// Keyed by the provider's key in the backend registry.
const PROVIDER_ICONS: Record<string, JSX.Element> = {
    github_actions: <IconGithub />,
    gitlab: <IconGitLab />,
    depot_ci: <img src={depotLogo} alt="" className="size-4" />,
}

export function WorkloadProviderIcon({ providerKey }: { providerKey: string }): JSX.Element | null {
    return PROVIDER_ICONS[providerKey] ?? null
}

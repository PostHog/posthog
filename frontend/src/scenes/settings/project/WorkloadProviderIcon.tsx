import { IconGitLab, IconGithub } from '@posthog/icons'

// Keyed by the provider's key in the backend registry.
const PROVIDER_ICONS: Record<string, JSX.Element> = {
    github_actions: <IconGithub />,
    gitlab: <IconGitLab />,
}

export function WorkloadProviderIcon({ providerKey }: { providerKey: string }): JSX.Element | null {
    return PROVIDER_ICONS[providerKey] ?? null
}

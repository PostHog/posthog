import { IconGithub } from '@posthog/icons'

// Keyed by the provider's key in the backend registry.
const PROVIDER_ICONS: Record<string, JSX.Element> = {
    github_actions: <IconGithub />,
}

export function WorkloadProviderIcon({ providerKey }: { providerKey: string }): JSX.Element | null {
    return PROVIDER_ICONS[providerKey] ?? null
}

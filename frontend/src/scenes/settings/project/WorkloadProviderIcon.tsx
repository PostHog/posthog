import { IconGithub } from '@posthog/icons'

import type { WorkloadProviderKeyEnumApi } from '~/generated/core/api.schemas'

const PROVIDER_ICONS: Record<WorkloadProviderKeyEnumApi, JSX.Element> = {
    github_actions: <IconGithub />,
}

export function WorkloadProviderIcon({ providerKey }: { providerKey: WorkloadProviderKeyEnumApi }): JSX.Element {
    return PROVIDER_ICONS[providerKey]
}

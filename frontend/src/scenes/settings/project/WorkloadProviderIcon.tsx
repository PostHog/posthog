import { IconGitLab, IconGithub, IconServer } from '@posthog/icons'

import type { WorkloadProviderKeyEnumApi } from '~/generated/core/api.schemas'

import depotLogo from 'public/services/depot.png'

const PROVIDER_ICONS: Record<WorkloadProviderKeyEnumApi, JSX.Element> = {
    github_actions: <IconGithub />,
    gitlab: <IconGitLab />,
    depot_ci: <img src={depotLogo} alt="" className="size-4" />,
    custom: <IconServer />,
}

export function WorkloadProviderIcon({ providerKey }: { providerKey: WorkloadProviderKeyEnumApi }): JSX.Element {
    return PROVIDER_ICONS[providerKey]
}

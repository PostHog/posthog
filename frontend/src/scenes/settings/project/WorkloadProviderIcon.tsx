import { IconGitLab, IconGithub } from '@posthog/icons'

import type { WorkloadProviderKeyEnumApi } from '~/generated/core/api.schemas'

import depotSymbolOnDark from 'public/services/depot-symbol-on-dark.svg'
import depotSymbolOnLight from 'public/services/depot-symbol-on-light.svg'

const PROVIDER_ICONS: Record<WorkloadProviderKeyEnumApi, JSX.Element> = {
    github_actions: <IconGithub />,
    gitlab: <IconGitLab />,
    depot_ci: (
        <>
            <img src={depotSymbolOnLight} alt="" className="size-4 dark:hidden" />
            <img src={depotSymbolOnDark} alt="" className="size-4 hidden dark:block" />
        </>
    ),
}

export function WorkloadProviderIcon({ providerKey }: { providerKey: WorkloadProviderKeyEnumApi }): JSX.Element {
    return PROVIDER_ICONS[providerKey]
}

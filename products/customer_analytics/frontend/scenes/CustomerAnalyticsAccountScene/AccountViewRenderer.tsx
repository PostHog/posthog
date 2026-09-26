import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { listAvailableAccountViewComponents } from '../../components/Accounts/accountViewComponents'
import type { AccountViewApi } from '../../generated/api.schemas'
import { parseAccountViewContent } from './accountViewDocument'
import { accountViewsLogic } from './accountViewsLogic'
import { AccountViewTile } from './AccountViewTile'

interface AccountViewRendererProps {
    view: AccountViewApi
    accountId: string
    externalId: string
    projectId: number
}

export function AccountViewRenderer({ view, accountId, externalId, projectId }: AccountViewRendererProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tileConfigReloads } = useValues(accountViewsLogic({ projectId }))
    const availableKinds = new Set(listAvailableAccountViewComponents(featureFlags).map((component) => component.kind))
    const components = parseAccountViewContent(view.content).filter((component) => availableKinds.has(component.kind))

    return (
        <div className="flex flex-col gap-3 py-3" data-attr="account-view-content">
            {components.map((component) => (
                <AccountViewTile
                    key={`${component.nodeId}:${tileConfigReloads[view.id] ?? 0}`}
                    view={view}
                    component={component}
                    componentCount={components.length}
                    projectId={projectId}
                    accountId={accountId}
                    externalId={externalId}
                />
            ))}
        </div>
    )
}

import { useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccountViewComponent } from '../../components/Accounts/AccountViewComponent'
import {
    getAccountViewComponentByKind,
    listAvailableAccountViewComponents,
} from '../../components/Accounts/accountViewComponents'
import type { AccountViewApi } from '../../generated/api.schemas'
import { parseAccountViewContent } from './accountViewDocument'

const SPAN_CLASSES: Record<number, string> = {
    1: '@min-[48rem]/account-view:col-span-1',
    2: '@min-[48rem]/account-view:col-span-2',
    3: '@min-[48rem]/account-view:col-span-3',
    4: '@min-[48rem]/account-view:col-span-4',
    5: '@min-[48rem]/account-view:col-span-5',
    6: '@min-[48rem]/account-view:col-span-6',
    7: '@min-[48rem]/account-view:col-span-7',
    8: '@min-[48rem]/account-view:col-span-8',
    9: '@min-[48rem]/account-view:col-span-9',
    10: '@min-[48rem]/account-view:col-span-10',
    11: '@min-[48rem]/account-view:col-span-11',
    12: '@min-[48rem]/account-view:col-span-12',
}

interface AccountViewRendererProps {
    view: AccountViewApi
    accountId: string
    externalId: string
}

export function AccountViewRenderer({ view, accountId, externalId }: AccountViewRendererProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const availableKinds = new Set(listAvailableAccountViewComponents(featureFlags).map((component) => component.kind))
    const components = parseAccountViewContent(view.content).filter((component) => availableKinds.has(component.kind))

    return (
        <div className="@container/account-view grid grid-cols-12 gap-3 py-3" data-attr="account-view-content">
            {components.map((component) => {
                const definition = getAccountViewComponentByKind(component.kind)
                return (
                    <LemonCard
                        key={component.nodeId}
                        hoverEffect={false}
                        className={`col-span-12 min-w-0 overflow-hidden p-0 ${SPAN_CLASSES[component.span] ?? SPAN_CLASSES[12]}`}
                    >
                        <div className="border-b px-2 py-1 text-xs font-medium text-secondary">{definition?.label}</div>
                        <div className="min-w-0 px-2 pt-2 pb-0 [&_.LemonTable]:-mx-2">
                            <AccountViewComponent
                                kind={component.kind}
                                accountId={accountId}
                                externalId={externalId}
                                embedded
                            />
                        </div>
                    </LemonCard>
                )
            })}
        </div>
    )
}

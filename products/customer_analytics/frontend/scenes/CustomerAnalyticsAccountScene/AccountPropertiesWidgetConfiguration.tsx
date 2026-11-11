import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type { AccountViewTileConfig } from '../../components/Accounts/accountViewTileConfig'
import { ACCOUNT_ID_FIELDS, ACCOUNT_LIST_FIELDS } from './accountNativeProperties'
import {
    accountWidgetKeysToReferences,
    getAccountWidgetProperties,
    getAccountWidgetPropertyKey,
} from './accountPropertiesWidgetConfig'
import { accountPropertyDataLogic } from './accountPropertyDataLogic'
import { accountSidebarConfigLogic } from './accountSidebarConfigLogic'
import { AccountPropertySelection } from './components/AccountPropertySelection'
import { MAX_PINNED_ACCOUNT_PROPERTIES, type AccountPropertyOption } from './components/accountPropertyTypes'

interface AccountPropertiesWidgetConfigurationProps {
    projectId: number
    accountId: string
    config: AccountViewTileConfig
    saving: boolean
    onChange: (config: AccountViewTileConfig) => void
}

export function AccountPropertiesWidgetConfiguration({
    projectId,
    accountId,
    config,
    saving,
    onChange,
}: AccountPropertiesWidgetConfigurationProps): JSX.Element {
    const definitionsLogic = accountSidebarConfigLogic({ projectId })
    const { availableDefinitions, availableDefinitionsLoading, availableDefinitionsLoadFailed } =
        useValues(definitionsLogic)
    const { loadAvailableDefinitions } = useActions(definitionsLogic)
    const { account } = useValues(accountPropertyDataLogic({ projectId, accountId }))
    const references = getAccountWidgetProperties(config)
    const options: AccountPropertyOption[] = [
        ...(availableDefinitions?.customProperties ?? []).map((definition) => ({
            key: `custom:${definition.id}`,
            label: definition.name,
            kind: 'custom' as const,
        })),
        ...(availableDefinitions?.relationships ?? []).map((definition) => ({
            key: `relationship:${definition.id}`,
            label: definition.name,
            kind: 'relationship' as const,
        })),
        ...[...ACCOUNT_ID_FIELDS, ...ACCOUNT_LIST_FIELDS]
            .filter((field) => field.key !== 'stripe_customer_id' || account?.properties?.stripe_customer_id)
            .map((field) => ({ key: `account:${field.key}`, label: field.label, kind: 'account' as const })),
    ]
    for (const reference of references) {
        const key = getAccountWidgetPropertyKey(reference)
        if (!options.some((option) => option.key === key)) {
            options.push({
                key,
                label:
                    reference.kind === 'account'
                        ? 'Stripe ID (not linked for this account)'
                        : 'Deleted property definition',
                kind:
                    reference.kind === 'custom_property'
                        ? 'custom'
                        : reference.kind === 'account'
                          ? 'account'
                          : 'relationship',
            })
        }
    }
    return (
        <div className="flex flex-col gap-2 ph-no-capture">
            <span className="font-semibold">Properties</span>
            {availableDefinitionsLoadFailed ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: loadAvailableDefinitions,
                        loading: availableDefinitionsLoading,
                    }}
                >
                    Could not load property definitions.
                </LemonBanner>
            ) : !availableDefinitions ? (
                <LemonSkeleton className="h-8" />
            ) : (
                <AccountPropertySelection
                    options={options}
                    selectedKeys={references.map(getAccountWidgetPropertyKey)}
                    saving={saving}
                    emptyLabel="No properties selected."
                    limitDisabledReason={`You can select up to ${MAX_PINNED_ACCOUNT_PROPERTIES} properties`}
                    onChange={(keys) => onChange({ ...config, properties: accountWidgetKeysToReferences(keys) })}
                />
            )}
        </div>
    )
}

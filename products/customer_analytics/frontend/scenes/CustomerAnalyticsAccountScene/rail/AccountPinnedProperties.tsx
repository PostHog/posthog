import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown, IconChevronRight, IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, LemonSkeleton } from '@posthog/lemon-ui'

import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountPropertyDescriptor } from '../accountDetailProperties'
import { accountDetailPropertiesLogic } from '../accountDetailPropertiesLogic'
import { AccountPropertyRow } from './AccountPropertyRow'

interface AccountPinnedPropertiesProps {
    accountId: string
    account: AccountApi
}

function pinMenuSection(
    title: string,
    descriptors: AccountPropertyDescriptor[],
    pinnedKeys: Set<string>,
    toggle: (key: string) => void
): LemonMenuItems[number] {
    return {
        title,
        items: descriptors.map((descriptor) => ({
            label: descriptor.label,
            icon: pinnedKeys.has(descriptor.key) ? <IconCheck /> : <span className="w-4" />,
            onClick: () => toggle(descriptor.key),
        })),
    }
}

export function AccountPinnedProperties({ accountId, account }: AccountPinnedPropertiesProps): JSX.Element {
    const logic = accountDetailPropertiesLogic({ accountId })
    const { descriptors, pinnedDescriptors, propertiesLoading, propertiesLoadFailed, showAllProperties } =
        useValues(logic)
    const { togglePinnedProperty, setShowAllProperties } = useActions(logic)

    const pinnedKeys = new Set(pinnedDescriptors.map((descriptor) => descriptor.key))
    const unpinned = descriptors.filter((descriptor) => !pinnedKeys.has(descriptor.key))
    const menuItems: LemonMenuItems = [
        pinMenuSection(
            'Custom properties',
            descriptors.filter((descriptor) => descriptor.kind === 'custom'),
            pinnedKeys,
            togglePinnedProperty
        ),
        pinMenuSection(
            'Relationships',
            descriptors.filter((descriptor) => descriptor.kind === 'relationship'),
            pinnedKeys,
            togglePinnedProperty
        ),
        pinMenuSection(
            'Account',
            descriptors.filter((descriptor) => descriptor.kind === 'field'),
            pinnedKeys,
            togglePinnedProperty
        ),
    ]

    return (
        <div className="flex flex-col gap-4 px-5 pt-4 pb-5" data-attr="account-pinned-properties">
            <div className="flex items-center">
                <span className="text-xxs font-semibold uppercase tracking-wider text-secondary">Properties</span>
                <LemonMenu items={menuItems} closeOnClickInside={false} placement="bottom-end">
                    <LemonButton
                        size="xsmall"
                        icon={<IconGear />}
                        className="ml-auto"
                        tooltip="Choose which properties are pinned"
                        aria-label="Configure pinned properties"
                        disabledReason={propertiesLoading ? 'Loading properties…' : undefined}
                        data-attr="account-configure-pinned-properties"
                    />
                </LemonMenu>
            </div>
            {propertiesLoading ? (
                <LemonSkeleton repeat={3} className="h-10 w-full" />
            ) : propertiesLoadFailed ? (
                <p className="text-sm text-secondary mb-0">Couldn't load properties. Try refreshing the page.</p>
            ) : descriptors.length === 0 ? (
                <p className="text-sm text-secondary mb-0">
                    No account properties defined yet. Add some in the customer analytics settings.
                </p>
            ) : (
                <>
                    {pinnedDescriptors.map((descriptor) => (
                        <AccountPropertyRow
                            key={descriptor.key}
                            accountId={accountId}
                            account={account}
                            descriptor={descriptor}
                        />
                    ))}
                    {showAllProperties
                        ? unpinned.map((descriptor) => (
                              <AccountPropertyRow
                                  key={descriptor.key}
                                  accountId={accountId}
                                  account={account}
                                  descriptor={descriptor}
                              />
                          ))
                        : null}
                    {unpinned.length > 0 ? (
                        <LemonButton
                            size="xsmall"
                            icon={showAllProperties ? <IconChevronDown /> : <IconChevronRight />}
                            onClick={() => setShowAllProperties(!showAllProperties)}
                            className="self-start -ml-1 text-secondary"
                            data-attr="account-show-all-properties"
                        >
                            {showAllProperties
                                ? 'Show pinned properties only'
                                : `Show all ${descriptors.length} properties`}
                        </LemonButton>
                    ) : null}
                </>
            )}
        </div>
    )
}

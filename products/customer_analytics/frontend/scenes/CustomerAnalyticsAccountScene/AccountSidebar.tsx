import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

import type { AccountApi } from '../../generated/api.schemas'
import {
    accountSidebarConfigLogic,
    configuratorKeysToPinnedProperties,
    pinnedPropertyToConfiguratorKey,
} from './accountSidebarConfigLogic'
import { AccountPinnedPropertiesEmptyState } from './components/AccountPinnedProperties'
import { AccountPropertyConfigurator } from './components/AccountPropertyConfigurator'
import type { AccountPropertyOption } from './components/accountPropertyTypes'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

export function AccountSidebar({ account }: { account: AccountApi }): JSX.Element {
    const { tagsSaving } = useValues(customerAnalyticsAccountSceneLogic)
    const { updateTags } = useActions(customerAnalyticsAccountSceneLogic)
    const { tags: tagsAvailable } = useValues(tagsModel)
    const { currentProjectId } = useValues(projectLogic)
    const configLogic = accountSidebarConfigLogic({ projectId: currentProjectId ?? 0 })
    const {
        availableDefinitions,
        availableDefinitionsLoadFailed,
        canSavePinnedProperties,
        config,
        configLoadFailed,
        configLoading,
        draftPinnedProperties,
        isConfiguring,
        stalePinnedProperties,
    } = useValues(configLogic)
    const {
        beginConfiguring,
        cancelConfiguring,
        loadAvailableDefinitions,
        loadConfig,
        savePinnedProperties,
        setDraftPinnedProperties,
    } = useActions(configLogic)

    const configurationLoadFailed = configLoadFailed || availableDefinitionsLoadFailed
    const configurationLoading = !configurationLoadFailed && (config === null || availableDefinitions === null)
    const pinnedPropertyCount = config?.pinned_properties.length ?? 0
    const propertyOptions: AccountPropertyOption[] = [
        ...(availableDefinitions?.customProperties ?? []).map((definition) => ({
            key: pinnedPropertyToConfiguratorKey({ kind: 'custom_property', id: definition.id }),
            label: definition.name,
            kind: 'custom' as const,
        })),
        ...(availableDefinitions?.relationships ?? []).map((definition) => ({
            key: pinnedPropertyToConfiguratorKey({ kind: 'relationship', id: definition.id }),
            label: definition.name,
            kind: 'relationship' as const,
        })),
    ]

    const reloadConfiguration = (): void => {
        loadConfig()
        loadAvailableDefinitions()
    }

    return (
        <aside
            className="w-full shrink-0 @max-[60rem]:border @max-[60rem]:rounded border-r rounded-r bg-surface-primary flex flex-col @min-[60rem]/account-detail:h-full @min-[60rem]/account-detail:min-h-0 @min-[60rem]/account-detail:w-60 @min-[60rem]/account-detail:overflow-y-auto"
            data-attr="account-sidebar"
        >
            <div className="flex flex-col gap-1 p-4" data-attr="account-rail-tags">
                <span className="secondary text-secondary">Tags</span>
                <ObjectTags
                    tags={account.tags ?? []}
                    onChange={updateTags}
                    saving={tagsSaving}
                    tagsAvailable={tagsAvailable}
                    wrap
                />
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-3 py-4" data-attr="account-rail-properties">
                <div className="flex items-center gap-2 px-4">
                    <span className="secondary text-secondary">Properties</span>
                    {!configurationLoading && !configurationLoadFailed && pinnedPropertyCount > 0 ? (
                        <LemonButton
                            size="xsmall"
                            icon={<IconGear />}
                            className="ml-auto"
                            tooltip="Choose pinned properties"
                            aria-label="Configure pinned properties"
                            onClick={beginConfiguring}
                            data-attr="account-configure-pinned-properties"
                        />
                    ) : null}
                </div>
                {configurationLoading ? (
                    <div className="flex flex-col gap-2 px-4" data-attr="account-pinned-properties-loading">
                        <LemonSkeleton className="h-4 w-full" />
                        <LemonSkeleton className="h-4 w-3/4" />
                    </div>
                ) : configurationLoadFailed ? (
                    <div className="px-4">
                        <LemonBanner type="error" action={{ children: 'Try again', onClick: reloadConfiguration }}>
                            Couldn't load pinned properties.
                        </LemonBanner>
                    </div>
                ) : pinnedPropertyCount === 0 ? (
                    <AccountPinnedPropertiesEmptyState onConfigure={beginConfiguring} />
                ) : (
                    <div className="flex flex-col gap-3 px-4">
                        <span className="text-xs text-muted">
                            {pinnedPropertyCount === 1
                                ? '1 property pinned.'
                                : `${pinnedPropertyCount} properties pinned.`}
                        </span>
                        {stalePinnedProperties.length > 0 ? (
                            <LemonBanner type="warning">
                                Some pinned properties are no longer available. Update your pins to remove them.
                            </LemonBanner>
                        ) : null}
                    </div>
                )}
            </div>
            <AccountPropertyConfigurator
                isOpen={isConfiguring}
                options={propertyOptions}
                pinnedPropertyKeys={draftPinnedProperties.map(pinnedPropertyToConfiguratorKey)}
                onChange={(keys) => setDraftPinnedProperties(configuratorKeysToPinnedProperties(keys))}
                onSave={() => savePinnedProperties()}
                onCancel={cancelConfiguring}
                saving={configLoading && config !== null}
                saveDisabledReason={!configLoading && !canSavePinnedProperties ? 'No changes to save' : undefined}
            />
        </aside>
    )
}

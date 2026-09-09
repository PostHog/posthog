import { useActions, useValues } from 'kea'

import { LemonBanner, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

import type { AccountApi } from '../../generated/api.schemas'
import {
    accountSidebarConfigLogic,
    configuratorKeysToPinnedProperties,
    pinnedPropertyToConfiguratorKey,
} from './accountSidebarConfigLogic'
import { accountSidebarPropertiesLogic } from './accountSidebarPropertiesLogic'
import { AccountPinnedProperties } from './components/AccountPinnedProperties'
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
        canSavePinnedProperties,
        config,
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
    const propertyLogic = accountSidebarPropertiesLogic({ accountId: account.id, projectId: currentProjectId ?? 0 })
    const {
        sidebarProperties,
        propertiesPanelState,
        propertiesRefreshFailed,
        propertySaveFailed,
        editingPropertyKey,
        savingPropertyKey,
        availableMembers,
        membersLoading,
    } = useValues(propertyLogic)
    const { loadPropertyData, editProperty, cancelEditing, saveCustomProperty, saveRelationship } =
        useActions(propertyLogic)
    const retryLoad = (): void => {
        loadConfig()
        loadAvailableDefinitions()
        loadPropertyData()
    }
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
            <div className="flex flex-col flex-1 min-h-0" data-attr="account-rail-properties">
                {propertiesPanelState !== 'ready' ? (
                    <div className="flex flex-col gap-3 p-4">
                        <span className="secondary text-secondary">Properties</span>
                        {propertiesPanelState === 'failed' ? (
                            <LemonBanner type="error" action={{ children: 'Try again', onClick: retryLoad }}>
                                Couldn't load pinned properties.
                            </LemonBanner>
                        ) : (
                            <div className="flex flex-col gap-2" data-attr="account-pinned-properties-loading">
                                <LemonSkeleton className="h-4 w-full" />
                                <LemonSkeleton className="h-4 w-3/4" />
                            </div>
                        )}
                    </div>
                ) : (
                    <>
                        {stalePinnedProperties.length > 0 ? (
                            <div className="px-4 pt-4">
                                <LemonBanner type="warning">
                                    Some pinned properties are no longer available. Update your pins to remove them.
                                </LemonBanner>
                            </div>
                        ) : null}
                        {propertySaveFailed ? (
                            <div className="px-4 pt-4">
                                <LemonBanner type="error">
                                    Couldn't save this property. Review the value and try again.
                                </LemonBanner>
                            </div>
                        ) : null}
                        {propertiesRefreshFailed ? (
                            <div className="px-4 pt-4">
                                <LemonBanner type="warning" action={{ children: 'Try again', onClick: retryLoad }}>
                                    Couldn't refresh pinned properties. These values might be out of date.
                                </LemonBanner>
                            </div>
                        ) : null}
                        <AccountPinnedProperties
                            properties={sidebarProperties}
                            editingPropertyKey={editingPropertyKey}
                            savingPropertyKey={savingPropertyKey}
                            availableMembers={availableMembers}
                            membersLoading={membersLoading}
                            onConfigure={beginConfiguring}
                            onEdit={(property) => {
                                if (!savingPropertyKey) {
                                    editProperty(property)
                                }
                            }}
                            onCancelEdit={() => {
                                if (!savingPropertyKey) {
                                    cancelEditing()
                                }
                            }}
                            onSaveCustomProperty={(property, value) => saveCustomProperty(property.key, value)}
                            onSaveRelationship={(property, memberIds) => saveRelationship(property.key, memberIds)}
                        />
                    </>
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

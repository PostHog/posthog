import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'

import {
    accountSidebarConfigLogic,
    configuratorKeysToPinnedProperties,
    pinnedPropertyToConfiguratorKey,
} from '../accountSidebarConfigLogic'
import { AccountPropertyEditSource, accountSidebarPropertiesLogic } from '../accountSidebarPropertiesLogic'
import { AccountPinnedProperties, AccountPinnedPropertiesProps } from './AccountPinnedProperties'
import { AccountPropertyConfigurator } from './AccountPropertyConfigurator'
import type { AccountPropertyOption } from './accountPropertyTypes'

export interface AccountPinnedPropertiesPanelProps {
    accountId: string
    layout?: AccountPinnedPropertiesProps['layout']
    source?: AccountPropertyEditSource
}

export function AccountPinnedPropertiesPanel({
    accountId,
    layout = 'vertical',
    source = 'account_sidebar',
}: AccountPinnedPropertiesPanelProps): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const projectId = currentProjectId ?? 0
    const configLogic = accountSidebarConfigLogic({ projectId })
    const {
        availableDefinitions,
        availableDefinitionsLoading,
        canSavePinnedProperties,
        config,
        configLoading,
        draftPinnedProperties,
        activeConfiguratorKey,
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
    const propertyLogic = accountSidebarPropertiesLogic({ accountId, projectId })
    const {
        sidebarProperties,
        propertiesPanelState,
        propertiesRefreshFailed,
        propertyDataLoading,
        propertySaveFailed,
        editingPropertyKey,
        savingPropertyKey,
        availableMembers,
        membersLoading,
    } = useValues(propertyLogic)
    const { loadPropertyData, editProperty, cancelEditing, saveCustomProperty, saveRelationship } =
        useActions(propertyLogic)
    const retryLoading = configLoading || availableDefinitionsLoading || propertyDataLoading
    const retryLoad = (): void => {
        if (!retryLoading) {
            loadConfig()
            loadAvailableDefinitions()
            loadPropertyData()
        }
    }
    const configuratorKey = `${source}:${accountId}`
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
        <div className="flex flex-col flex-1 min-h-0" data-attr="account-rail-properties">
            {propertiesPanelState !== 'ready' ? (
                <div className="flex flex-col gap-3 p-4">
                    <span className="secondary text-secondary">Properties</span>
                    {propertiesPanelState === 'failed' ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: retryLoad, loading: retryLoading }}
                        >
                            Could not load pinned properties.
                        </LemonBanner>
                    ) : (
                        <div
                            className={clsx('flex gap-2', layout === 'horizontal' ? 'flex-wrap' : 'flex-col')}
                            data-attr="account-pinned-properties-loading"
                        >
                            <LemonSkeleton className={layout === 'horizontal' ? 'h-10 w-48' : 'h-4 w-full'} />
                            <LemonSkeleton className={layout === 'horizontal' ? 'h-10 w-48' : 'h-4 w-3/4'} />
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
                                Could not save this property. Review the value and try again.
                            </LemonBanner>
                        </div>
                    ) : null}
                    {propertiesRefreshFailed ? (
                        <div className="px-4 pt-4">
                            <LemonBanner
                                type="warning"
                                action={{ children: 'Try again', onClick: retryLoad, loading: retryLoading }}
                            >
                                Could not refresh pinned properties. These values may be out of date.
                            </LemonBanner>
                        </div>
                    ) : null}
                    <AccountPinnedProperties
                        properties={sidebarProperties}
                        layout={layout}
                        editingPropertyKey={editingPropertyKey}
                        savingPropertyKey={savingPropertyKey}
                        availableMembers={availableMembers}
                        membersLoading={membersLoading}
                        onConfigure={() => beginConfiguring(configuratorKey)}
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
                        onSaveCustomProperty={(property, value) => saveCustomProperty(property.key, value, source)}
                        onSaveRelationship={(property, memberIds) => saveRelationship(property.key, memberIds, source)}
                    />
                </>
            )}
            <AccountPropertyConfigurator
                isOpen={activeConfiguratorKey === configuratorKey}
                options={propertyOptions}
                pinnedPropertyKeys={draftPinnedProperties.map(pinnedPropertyToConfiguratorKey)}
                onChange={(keys) => setDraftPinnedProperties(configuratorKeysToPinnedProperties(keys))}
                onSave={() => savePinnedProperties()}
                onCancel={cancelConfiguring}
                saving={configLoading && config !== null}
                saveDisabledReason={!configLoading && !canSavePinnedProperties ? 'No changes to save' : undefined}
            />
        </div>
    )
}

import { useActions, useMountedLogic, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { userHasAccess } from 'lib/utils/accessControlUtils'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { canEditEmailMatching } from '../../../components/Accounts/accountEmailMatching'
import type { AccountViewTileLogicProps } from '../../../components/Accounts/accountViewTileConfig'
import {
    ACCOUNT_FIELDS,
    accountFieldToPropertyKey,
    accountPropertiesTileLogic,
    propertyKeyToAccountField,
} from '../accountPropertiesTileLogic'
import { accountSidebarConfigLogic, pinnedPropertyToConfiguratorKey } from '../accountSidebarConfigLogic'
import { accountSidebarPropertiesLogic } from '../accountSidebarPropertiesLogic'
import { customerAnalyticsAccountSceneLogic, isAccountListField } from '../customerAnalyticsAccountSceneLogic'
import { AccountFieldProperty } from './AccountFieldProperty'
import { AccountPropertyConfigurator } from './AccountPropertyConfigurator'
import { AccountPropertyField } from './AccountPropertyField'
import type { AccountPropertyOption } from './accountPropertyTypes'

export interface AccountPropertiesTileProps extends AccountViewTileLogicProps {
    accountId: string
}

export function AccountPropertiesTile({
    accountId,
    instanceId,
    initialConfig,
    onConfigChange,
}: AccountPropertiesTileProps): JSX.Element {
    const editorScope = `account_view:${instanceId ?? accountId}`
    const { currentProjectId } = useValues(projectLogic)
    const projectId = currentProjectId ?? 0
    const tileLogic = accountPropertiesTileLogic({ accountId, projectId, instanceId, initialConfig, onConfigChange })
    const { propertyKeys, draftPropertyKeys, configuratorOpen } = useValues(tileLogic)
    const { openConfigurator, closeConfigurator, setDraftPropertyKeys, savePropertyKeys } = useActions(tileLogic)
    const configLogic = accountSidebarConfigLogic({ projectId })
    useMountedLogic(configLogic)
    const { availableDefinitions, availableDefinitionsLoadFailed, availableDefinitionsLoading } = useValues(configLogic)
    const { loadAvailableDefinitions } = useActions(configLogic)
    const propertyLogic = accountSidebarPropertiesLogic({ accountId, projectId })
    const {
        accountProperties,
        propertyData,
        propertyDataLoadFailed,
        propertyDataLoading,
        editingPropertyKey,
        editingScope,
        savingPropertyKey,
        propertySaveFailed,
        availableMembers,
        membersLoading,
    } = useValues(propertyLogic)
    const { loadPropertyData, editProperty, cancelEditing, saveCustomProperty, saveRelationship } =
        useActions(propertyLogic)

    const { account, accountFieldEditor, savingAccountField, accountFieldSaveFailed } = useValues(
        customerAnalyticsAccountSceneLogic
    )
    const { editAccountField, cancelAccountFieldEdit, saveAccountField } = useActions(
        customerAnalyticsAccountSceneLogic
    )
    const { currentTeam } = useValues(teamLogic)

    const canEdit = userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Editor)
    const hasStripeId = !!account?.properties?.stripe_customer_id
    const visibleFields = ACCOUNT_FIELDS.filter(({ key }) => key !== 'stripe_customer_id' || hasStripeId)
    const propertyOptions: AccountPropertyOption[] = [
        ...visibleFields.map((field) => ({
            key: accountFieldToPropertyKey(field.key),
            label: field.label,
            kind: 'custom' as const,
        })),
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
    const propertiesByKey = new Map(accountProperties.map((property) => [property.key, property]))
    const needsPropertyData = propertyKeys.some((key) => propertyKeyToAccountField(key) === null)
    const loading = !account || (needsPropertyData && (availableDefinitions === null || propertyData === null))
    const loadFailed = needsPropertyData && (availableDefinitionsLoadFailed || propertyDataLoadFailed)
    const missingKeyCount = propertyKeys.filter((key) => {
        const field = propertyKeyToAccountField(key)
        return field ? !visibleFields.some(({ key: visible }) => visible === field) : !propertiesByKey.has(key)
    }).length
    const editingHere = editingScope === editorScope
    const retryLoading = availableDefinitionsLoading || propertyDataLoading
    const retryLoad = (): void => {
        if (!retryLoading) {
            loadAvailableDefinitions()
            loadPropertyData()
        }
    }

    const renderRows = (): JSX.Element => (
        <div className="flex flex-col gap-3" data-attr="account-view-properties-list">
            {propertyKeys.map((key) => {
                const field = propertyKeyToAccountField(key)
                if (field) {
                    const definition = visibleFields.find((candidate) => candidate.key === field)
                    if (!definition || !account) {
                        return null
                    }
                    const isList = isAccountListField(field)
                    const editing = accountFieldEditor?.key === field && accountFieldEditor.scope === editorScope
                    return (
                        <AccountFieldProperty
                            key={key}
                            label={definition.label}
                            value={isList ? (account.properties?.[field] ?? []) : (account.properties?.[field] ?? '')}
                            placeholder={definition.placeholder}
                            editing={editing}
                            saving={savingAccountField === field}
                            editDisabledReason={
                                !canEdit
                                    ? 'You need editor access to change this value'
                                    : isList && !canEditEmailMatching(currentTeam)
                                      ? 'Only project admins can edit email domains and known emails'
                                      : savingAccountField
                                        ? 'Saving another value'
                                        : undefined
                            }
                            onEdit={() => editAccountField(field, editorScope)}
                            onCancel={cancelAccountFieldEdit}
                            onSave={(value) => saveAccountField(field, value)}
                        />
                    )
                }
                const property = propertiesByKey.get(key)
                if (!property) {
                    return null
                }
                return (
                    <AccountPropertyField
                        key={key}
                        property={property}
                        editing={editingHere && editingPropertyKey === key}
                        saving={savingPropertyKey === key}
                        availableMembers={availableMembers}
                        membersLoading={membersLoading}
                        onEdit={() => {
                            if (!savingPropertyKey) {
                                editProperty(property, editorScope)
                            }
                        }}
                        onCancel={() => {
                            if (!savingPropertyKey) {
                                cancelEditing()
                            }
                        }}
                        onSaveCustomProperty={(row, value) => saveCustomProperty(row.key, value, 'account_view')}
                        onSaveRelationship={(row, memberIds) => saveRelationship(row.key, memberIds, 'account_view')}
                    />
                )
            })}
        </div>
    )

    return (
        <div className="flex flex-col gap-3 pb-2" data-attr="account-view-properties">
            {propertyKeys.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-4 text-center">
                    <p className="text-sm text-secondary mb-0">
                        {onConfigChange
                            ? 'Choose the account properties to show and edit here.'
                            : 'No properties are chosen for this tile yet.'}
                    </p>
                    {onConfigChange ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={openConfigurator}
                            data-attr="account-view-properties-choose-empty"
                        >
                            Choose properties
                        </LemonButton>
                    ) : null}
                </div>
            ) : (
                <>
                    {onConfigChange ? (
                        <div className="flex justify-end">
                            <LemonButton
                                size="xsmall"
                                icon={<IconGear />}
                                tooltip="Choose properties"
                                aria-label="Choose properties"
                                onClick={openConfigurator}
                                data-attr="account-view-properties-configure"
                            />
                        </div>
                    ) : null}
                    {loadFailed && loading ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: retryLoad, loading: retryLoading }}
                        >
                            Could not load these properties.
                        </LemonBanner>
                    ) : loading ? (
                        <div className="flex flex-col gap-2" data-attr="account-view-properties-loading">
                            <LemonSkeleton className="h-4 w-full" />
                            <LemonSkeleton className="h-4 w-3/4" />
                        </div>
                    ) : (
                        <>
                            {missingKeyCount > 0 ? (
                                <LemonBanner type="warning">
                                    Some properties are no longer available. Choose properties to update this tile.
                                </LemonBanner>
                            ) : null}
                            {(propertySaveFailed && editingHere) ||
                            (accountFieldSaveFailed && accountFieldEditor?.scope === editorScope) ? (
                                <LemonBanner type="error">
                                    Could not save this property. Review the value and try again.
                                </LemonBanner>
                            ) : null}
                            {renderRows()}
                        </>
                    )}
                </>
            )}
            <AccountPropertyConfigurator
                isOpen={configuratorOpen}
                title="Choose properties"
                options={propertyOptions}
                pinnedPropertyKeys={draftPropertyKeys}
                onChange={setDraftPropertyKeys}
                onSave={savePropertyKeys}
                onCancel={closeConfigurator}
            />
        </div>
    )
}

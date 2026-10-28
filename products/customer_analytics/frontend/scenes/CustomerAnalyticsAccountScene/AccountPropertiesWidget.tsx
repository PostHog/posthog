import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'

import type { AccountViewTileLogicProps } from '../../components/Accounts/accountViewTileConfig'
import type { PinnedAccountPropertyApi } from '../../generated/api.schemas'
import { getAccountWidgetPropertyKey } from './accountPropertiesWidgetConfig'
import { accountPropertiesWidgetLogic } from './accountPropertiesWidgetLogic'
import { useAccountPropertiesViewport } from './accountPropertiesWidgetViewport'
import { accountSidebarConfigLogic } from './accountSidebarConfigLogic'
import { accountSidebarPropertiesLogic } from './accountSidebarPropertiesLogic'
import { AccountNativePropertyField } from './components/AccountNativePropertyField'
import { AccountPropertyField } from './components/AccountPropertyField'

interface AccountPropertiesWidgetProps extends AccountViewTileLogicProps {
    accountId: string
    projectId?: number
}

export function AccountPropertiesWidget({
    accountId,
    projectId: suppliedProjectId,
    instanceId,
    initialConfig,
    onConfigChange,
}: AccountPropertiesWidgetProps): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const { contentRef, maxHeight } = useAccountPropertiesViewport()
    const projectId = suppliedProjectId ?? currentProjectId ?? 0
    const nativeLogic = accountPropertiesWidgetLogic({
        projectId,
        accountId,
        instanceId,
        initialConfig,
        onConfigChange,
    })
    const {
        references,
        account,
        accountLoading,
        accountLoadFailed,
        nativeEditingKey,
        nativeDraft,
        nativeSaveFailed,
        savedAccountLoading,
        canEditNativeProperties,
        canEditMatching,
    } = useValues(nativeLogic)
    const { editNativeProperty, cancelNativeEditing, setNativeDraft, saveNativeProperty, loadAccount } =
        useActions(nativeLogic)
    const propertyReferences = references.filter(
        (reference): reference is PinnedAccountPropertyApi => reference.kind !== 'account'
    )
    const propertyLogic = accountSidebarPropertiesLogic({
        projectId,
        accountId,
        instanceId: `view:${instanceId ?? 'default'}`,
        propertyReferences,
    })
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
    const definitionsLogic = accountSidebarConfigLogic({ projectId })
    const { availableDefinitionsLoading } = useValues(definitionsLogic)
    const { loadAvailableDefinitions } = useActions(definitionsLogic)
    const hasNativeProperties = references.some((reference) => reference.kind === 'account')
    const hasPropertyReferences = propertyReferences.length > 0
    const retryLoading =
        (hasNativeProperties && accountLoading) ||
        (hasPropertyReferences && (propertyDataLoading || availableDefinitionsLoading))
    const saving = !!savingPropertyKey || savedAccountLoading
    const retry = (): void => {
        if (
            (hasNativeProperties && nativeLogic.values.accountLoading) ||
            (hasPropertyReferences &&
                (propertyLogic.values.propertyDataLoading || definitionsLogic.values.availableDefinitionsLoading))
        ) {
            return
        }
        if (hasNativeProperties) {
            loadAccount()
        }
        if (hasPropertyReferences) {
            loadPropertyData()
            loadAvailableDefinitions()
        }
    }
    const failed =
        (hasPropertyReferences && propertiesPanelState === 'failed') ||
        (hasNativeProperties && !account && accountLoadFailed)
    const loading =
        !failed && ((hasPropertyReferences && propertiesPanelState === 'loading') || (hasNativeProperties && !account))
    if (references.length === 0) {
        return (
            <p className="text-secondary text-sm pb-2">
                No properties selected. Use the tile's Edit action to choose properties.
            </p>
        )
    }
    if (failed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: retry, loading: retryLoading }}>
                Could not load properties.
            </LemonBanner>
        )
    }
    if (loading) {
        return (
            <div className="flex flex-col gap-2 pb-2" data-attr="account-properties-widget-loading">
                <LemonSkeleton className="h-8" />
                <LemonSkeleton className="h-8" />
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-3 min-w-0 pb-3 ph-no-capture" data-attr="account-properties-widget">
            {propertySaveFailed || nativeSaveFailed ? (
                <LemonBanner type="error">
                    Could not save this property. Your input is kept. Review the value and try Save again.
                </LemonBanner>
            ) : null}
            {(hasPropertyReferences && propertiesRefreshFailed) || (hasNativeProperties && accountLoadFailed) ? (
                <LemonBanner type="warning" action={{ children: 'Try again', onClick: retry, loading: retryLoading }}>
                    Could not refresh properties. These values may be out of date.
                </LemonBanner>
            ) : null}
            <div
                className="min-w-0 -mr-4 pr-4 overflow-y-auto [scrollbar-gutter:stable]"
                style={maxHeight === null ? undefined : { maxHeight }}
                {...(maxHeight === null ? {} : { role: 'region', 'aria-label': 'Properties', tabIndex: 0 })}
                data-attr="account-properties-widget-list"
            >
                <div ref={contentRef} className="relative flex flex-col gap-3 min-w-0">
                    {references.map((reference) => {
                        const key = getAccountWidgetPropertyKey(reference)
                        if (reference.kind === 'account') {
                            if (reference.key === 'stripe_customer_id' && !account?.properties?.stripe_customer_id) {
                                return null
                            }
                            const list = reference.key === 'email_domains' || reference.key === 'known_emails'
                            const disabledReason = !canEditNativeProperties
                                ? 'You need editor access to edit account properties.'
                                : list && !canEditMatching
                                  ? 'Only project admins can edit email domains and known emails.'
                                  : undefined
                            return (
                                <AccountNativePropertyField
                                    key={key}
                                    propertyKey={reference.key}
                                    value={account?.properties?.[reference.key] ?? (list ? [] : '')}
                                    draft={nativeDraft}
                                    editing={nativeEditingKey === reference.key}
                                    saving={savedAccountLoading}
                                    disabledReason={disabledReason}
                                    onEdit={() => {
                                        if (!saving && !disabledReason) {
                                            cancelEditing()
                                            editNativeProperty(reference.key)
                                        }
                                    }}
                                    onChange={setNativeDraft}
                                    onSave={saveNativeProperty}
                                    onCancel={() => {
                                        if (!saving) {
                                            cancelNativeEditing()
                                        }
                                    }}
                                />
                            )
                        }
                        const property = sidebarProperties.find((property) => property.key === key)
                        return property ? (
                            <AccountPropertyField
                                key={key}
                                property={property}
                                editing={editingPropertyKey === key}
                                saving={savingPropertyKey === key}
                                availableMembers={availableMembers}
                                membersLoading={membersLoading}
                                onEdit={() => {
                                    if (!saving) {
                                        cancelNativeEditing()
                                        editProperty(property)
                                    }
                                }}
                                onCancel={() => {
                                    if (
                                        !propertyLogic.values.savingPropertyKey &&
                                        !nativeLogic.values.savedAccountLoading
                                    ) {
                                        cancelEditing()
                                    }
                                }}
                                onSaveCustomProperty={(property, value) =>
                                    saveCustomProperty(property.key, value, 'account_view')
                                }
                                onSaveRelationship={(property, memberIds) =>
                                    saveRelationship(property.key, memberIds, 'account_view')
                                }
                            />
                        ) : (
                            <LemonBanner key={key} type="warning">
                                This property definition was deleted. Use the tile's Edit action to remove it.
                            </LemonBanner>
                        )
                    })}
                </div>
            </div>
            {references.every((reference) => reference.kind === 'account' && reference.key === 'stripe_customer_id') &&
            !account?.properties?.stripe_customer_id ? (
                <p className="text-secondary text-sm mb-0">
                    Stripe ID is not linked for this account. Use the tile's Edit action to choose another property.
                </p>
            ) : null}
        </div>
    )
}

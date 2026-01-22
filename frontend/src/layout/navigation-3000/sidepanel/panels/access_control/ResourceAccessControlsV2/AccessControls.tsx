import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonDialog, LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { membersLogic } from 'scenes/organization/membersLogic'

import { AvailableFeature } from '~/types'

import { resourcesAccessControlLogic } from '../resourcesAccessControlLogic'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { AccessControlFilters } from './AccessControlFilters'
import { AccessControlRuleModal } from './AccessControlRuleModal'
import { AccessControlTable } from './AccessControlTable'
import { accessControlsLogic } from './accessControlsLogic'
import { scopeTypeForAccessControlsTab } from './helpers'
import { AccessControlRow, AccessControlsTab } from './types'

export function AccessControls({ projectId }: { projectId: string }): JSX.Element {
    useMountedLogic(membersLogic)
    useMountedLogic(roleAccessControlLogic)
    useMountedLogic(resourcesAccessControlLogic)

    const logic = accessControlsLogic({ projectId })

    const {
        activeTab,
        searchText,
        filters,
        ruleModalState,
        canUseRoles,
        allMembers,
        resourcesWithProject,
        ruleOptions,
        filteredSortedRows,
        hasRuleConflict,
        availableLevelsForResource,
        levelOptionsForResource,
        canEditAny,
        loading,
        roles,
        canEditAccessControls,
        canEditRoleBasedAccessControls,
    } = useValues(logic)

    const { setActiveTab, setSearchText, setFilters, openRuleModal, closeRuleModal, deleteRule, saveRule } =
        useActions(logic)

    function confirmDelete(row: AccessControlRow): void {
        LemonDialog.open({
            title: 'Delete rule',
            description: `Remove this rule for ${row.scopeLabel} → ${row.resourceLabel}?`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteRule(row),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const showRolesError = activeTab === 'roles' && !canUseRoles

    return (
        <>
            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <div className="space-y-4">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        tabs={[
                            { key: 'defaults' as AccessControlsTab, label: 'Defaults' },
                            {
                                key: 'roles' as AccessControlsTab,
                                label: 'Roles',
                                tooltip: !canUseRoles ? 'Requires role-based access' : undefined,
                            },
                            { key: 'members' as AccessControlsTab, label: 'Members' },
                        ]}
                    />

                    {showRolesError ? (
                        <LemonBanner type="error">
                            You must upgrade your plan to use role-based access control.
                        </LemonBanner>
                    ) : (
                        <>
                            <AccessControlFilters
                                activeTab={activeTab}
                                searchText={searchText}
                                setSearchText={setSearchText}
                                filters={filters}
                                setFilters={setFilters}
                                roles={roles ?? []}
                                members={allMembers}
                                resources={resourcesWithProject}
                                ruleOptions={ruleOptions}
                                canUseRoles={canUseRoles}
                                canEditAny={canEditAny}
                                onAdd={() =>
                                    openRuleModal({
                                        mode: 'add',
                                        initialScopeType: scopeTypeForAccessControlsTab(activeTab),
                                    })
                                }
                            />

                            <AccessControlTable
                                activeTab={activeTab}
                                rows={filteredSortedRows}
                                loading={loading}
                                canEditAccessControls={canEditAccessControls}
                                canEditRoleBasedAccessControls={canEditRoleBasedAccessControls}
                                onEdit={(row) => openRuleModal({ mode: 'edit', row })}
                                onDelete={confirmDelete}
                            />
                        </>
                    )}
                </div>
            </PayGateMini>

            {ruleModalState && (
                <AccessControlRuleModal
                    state={ruleModalState}
                    close={closeRuleModal}
                    canUseRoles={canUseRoles}
                    roles={roles ?? []}
                    members={allMembers}
                    resources={resourcesWithProject}
                    availableLevelsForResource={availableLevelsForResource}
                    levelOptionsForResource={levelOptionsForResource}
                    canEditAccessControls={canEditAccessControls ?? false}
                    canEditRoleBasedAccessControls={canEditRoleBasedAccessControls ?? false}
                    onSave={saveRule}
                    loading={loading}
                    projectId={projectId}
                    hasRuleConflict={hasRuleConflict}
                />
            )}
        </>
    )
}

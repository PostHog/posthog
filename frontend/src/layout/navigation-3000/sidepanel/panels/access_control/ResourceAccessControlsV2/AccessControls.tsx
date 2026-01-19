import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonDialog, LemonTabs } from '@posthog/lemon-ui'

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
import { AccessControlRow } from './types'

export function AccessControls({ projectId }: { projectId: string }): JSX.Element {
    useMountedLogic(membersLogic)
    useMountedLogic(roleAccessControlLogic)
    useMountedLogic(resourcesAccessControlLogic)

    const logic = accessControlsLogic({ projectId })

    const {
        activeTab,
        searchText,
        selectedRoleIds,
        selectedMemberIds,
        selectedResourceKeys,
        selectedRuleLevels,
        ruleModalState,
        canUseRoles,
        allMembers,
        resourcesWithProject,
        ruleOptions,
        filteredSortedRows,
        canEditAny,
        loading,
        roles,
        projectAvailableLevels,
        resourceAvailableLevels,
        canEditAccessControls,
        canEditRoleBasedAccessControls,
    } = useValues(logic)

    const {
        setActiveTab,
        setSearchText,
        setSelectedRoleIds,
        setSelectedMemberIds,
        setSelectedResourceKeys,
        setSelectedRuleLevels,
        openRuleModal,
        closeRuleModal,
        deleteRule,
        saveRule,
    } = useActions(logic)

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

    return (
        <>
            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <div className="space-y-4">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        tabs={[
                            { key: 'defaults', label: 'Defaults' },
                            {
                                key: 'roles',
                                label: 'Roles',
                                tooltip: !canUseRoles ? 'Requires role-based access' : undefined,
                            },
                            { key: 'members', label: 'Members' },
                        ]}
                    />

                    <AccessControlFilters
                        activeTab={activeTab}
                        searchText={searchText}
                        setSearchText={setSearchText}
                        selectedRoleIds={selectedRoleIds}
                        setSelectedRoleIds={setSelectedRoleIds}
                        selectedMemberIds={selectedMemberIds}
                        setSelectedMemberIds={setSelectedMemberIds}
                        selectedResourceKeys={selectedResourceKeys}
                        setSelectedResourceKeys={setSelectedResourceKeys}
                        selectedRuleLevels={selectedRuleLevels}
                        setSelectedRuleLevels={setSelectedRuleLevels}
                        roles={roles ?? []}
                        members={allMembers}
                        resources={resourcesWithProject}
                        ruleOptions={ruleOptions}
                        canUseRoles={canUseRoles}
                        canEditAny={canEditAny}
                        onAddClick={() =>
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
                </div>
            </PayGateMini>

            {ruleModalState ? (
                <AccessControlRuleModal
                    state={ruleModalState}
                    close={closeRuleModal}
                    canUseRoles={canUseRoles}
                    roles={roles ?? []}
                    members={allMembers}
                    resources={resourcesWithProject}
                    projectAvailableLevels={projectAvailableLevels}
                    resourceAvailableLevels={resourceAvailableLevels}
                    canEditAccessControls={canEditAccessControls}
                    canEditRoleBasedAccessControls={canEditRoleBasedAccessControls}
                    onSave={saveRule}
                    loading={loading}
                />
            ) : null}
        </>
    )
}

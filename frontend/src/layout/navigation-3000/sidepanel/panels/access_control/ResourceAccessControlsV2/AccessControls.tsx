import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { membersLogic } from 'scenes/organization/membersLogic'

import { AvailableFeature } from '~/types'

import { resourcesAccessControlLogic } from '../resourcesAccessControlLogic'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { AccessControlDefaultSettings } from './AccessControlDefaultSettings'
import { AccessControlFilters } from './AccessControlFilters'
import { AccessControlTable } from './AccessControlTable'
import { GroupedAccessControlRuleModal } from './GroupedAccessControlRuleModal'
import { accessControlsLogic } from './accessControlsLogic'
import type { AccessControlsTab } from './types'

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
        getLevelOptionsForResource,
        canEditAny,
        loading,
        roles,
        canEditAccessControls,
        canEditRoleBasedAccessControls,
    } = useValues(logic)

    const { setActiveTab, setSearchText, setFilters, openRuleModal, closeRuleModal, saveGroupedRules } =
        useActions(logic)

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
                        <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS} />
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
                            />

                            {activeTab === 'defaults' ? (
                                <AccessControlDefaultSettings projectId={projectId} />
                            ) : (
                                <AccessControlTable
                                    activeTab={activeTab}
                                    rows={filteredSortedRows}
                                    loading={loading}
                                    canEditAny={canEditAny}
                                    onEdit={(row) => openRuleModal({ row })}
                                />
                            )}
                        </>
                    )}
                </div>
            </PayGateMini>

            {ruleModalState && (
                <GroupedAccessControlRuleModal
                    state={ruleModalState}
                    close={closeRuleModal}
                    resources={resourcesWithProject}
                    loading={loading}
                    projectId={projectId}
                    getLevelOptionsForResource={getLevelOptionsForResource}
                    canEdit={
                        ruleModalState.row.id === 'default' ? !!canEditAccessControls : !!canEditRoleBasedAccessControls
                    }
                    onSave={saveGroupedRules}
                />
            )}
        </>
    )
}

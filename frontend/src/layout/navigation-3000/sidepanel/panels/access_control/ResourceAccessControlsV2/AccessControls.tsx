import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AvailableFeature } from '~/types'

import { AccessControlDefaultSettings } from './AccessControlDefaultSettings'
import { AccessControlFilters } from './AccessControlFilters'
import { AccessControlTable } from './AccessControlTable'
import { GroupedAccessControlRuleModal } from './GroupedAccessControlRuleModal'
import { accessControlsLogic } from './accessControlsLogic'
import type { AccessControlsTab } from './types'

export function AccessControls({ projectId }: { projectId: string }): JSX.Element {
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
        ruleModalMemberIsOrgAdmin,
        ruleModalMemberHasAdminAccess,
        ruleModalRoleHasAdminAccess,
    } = useValues(logic)

    const { setActiveTab, setSearchText, setFilters, openRuleModal, closeRuleModal, saveGroupedRules } =
        useActions(logic)

    return (
        <>
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

                <AccessControlTabContainer activeTab={activeTab}>
                    {activeTab === 'defaults' ? (
                        <AccessControlDefaultSettings projectId={projectId} />
                    ) : (
                        <div className="space-y-4">
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
                            <AccessControlTable
                                activeTab={activeTab}
                                rows={filteredSortedRows}
                                loading={loading}
                                canEditAny={canEditAny}
                                onEdit={(row) => openRuleModal({ row })}
                            />
                        </div>
                    )}
                </AccessControlTabContainer>
            </div>

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
                    memberIsOrgAdmin={ruleModalMemberIsOrgAdmin}
                    memberHasAdminAccess={ruleModalMemberHasAdminAccess}
                    roleHasAdminAccess={ruleModalRoleHasAdminAccess}
                />
            )}
        </>
    )
}

function AccessControlTabContainer(props: { activeTab: AccessControlsTab; children?: React.ReactNode }): JSX.Element {
    if (props.activeTab === 'roles') {
        return (
            <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>{props.children}</PayGateMini>
            </PayGateMini>
        )
    }
    if (props.activeTab === 'members') {
        return <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>{props.children}</PayGateMini>
    }

    return <>{props.children}</>
}

import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AvailableFeature, SidePanelTab } from '~/types'

import { AccessControlDefaultSettings } from './AccessControlDefaultSettings'
import { AccessControlDetail } from './AccessControlDetail'
import { AccessControlFilters } from './AccessControlFilters'
import { accessControlsLogic } from './accessControlsLogic'
import { AccessControlTable } from './AccessControlTable'
import { getEntryId } from './helpers'
import type { AccessControlsTab, ScopeType } from './types'

export function AccessControls({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })

    const {
        activeTab,
        searchText,
        filters,
        canUseRoles,
        allMembers,
        roles,
        resourcesWithProject,
        ruleOptions,
        filteredRoles,
        filteredMembers,
        canEdit,
        loading,
        selectedMemberId,
        selectedRoleId,
    } = useValues(logic)

    const { setActiveTab, setSearchText, setFilters } = useActions(logic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { selectedTab, selectedTabOptions, sidePanelOpen } = useValues(sidePanelStateLogic)

    const scopeType: ScopeType = activeTab === 'roles' ? 'role' : 'member'

    // Highlight the row whose detail is open in the side panel
    const openInPanelId =
        sidePanelOpen && selectedTab === SidePanelTab.AccessDetail && selectedTabOptions?.startsWith(`${scopeType}:`)
            ? selectedTabOptions.slice(scopeType.length + 1)
            : null

    // A member or role is being inspected — take over the whole section with their detail page
    if (activeTab === 'members' && selectedMemberId) {
        return <AccessControlDetail projectId={projectId} scopeType="member" />
    }
    if (activeTab === 'roles' && selectedRoleId) {
        return <AccessControlDetail projectId={projectId} scopeType="role" />
    }

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
                                entries={activeTab === 'roles' ? filteredRoles : filteredMembers}
                                loading={loading}
                                canEditAny={canEdit}
                                selectedEntryId={openInPanelId}
                                onEdit={(entry) =>
                                    openSidePanel(SidePanelTab.AccessDetail, `${scopeType}:${getEntryId(entry)}`)
                                }
                            />
                        </div>
                    )}
                </AccessControlTabContainer>
            </div>
        </>
    )
}

function AccessControlTabContainer(props: { activeTab: AccessControlsTab; children?: React.ReactNode }): JSX.Element {
    if (props.activeTab === 'roles') {
        return (
            <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS}>
                <PayGateMini feature={AvailableFeature.ACCESS_CONTROL}>{props.children}</PayGateMini>
            </PayGateMini>
        )
    }
    if (props.activeTab === 'members') {
        return <PayGateMini feature={AvailableFeature.ACCESS_CONTROL}>{props.children}</PayGateMini>
    }

    return <>{props.children}</>
}

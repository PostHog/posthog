import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AvailableFeature, SidePanelTab } from '~/types'

import { AccessControlDefaultSettings } from './AccessControlDefaultSettings'
import { AccessControlFilters } from './AccessControlFilters'
import { accessControlsLogic } from './accessControlsLogic'
import { AccessControlTable } from './AccessControlTable'
import { GroupedAccessControlRuleModal } from './GroupedAccessControlRuleModal'
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
        activePanelSubject,
        visibleResourceKeySet,
        filteredResourceKeySet,
        accessDetailPanelEnabled,
        ruleModalState,
    } = useValues(logic)

    const { setActiveTab, setSearchText, setFilters, openAccessDetailPanel, openRuleModal } = useActions(logic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { selectedTab, sidePanelOpen } = useValues(sidePanelStateLogic)

    const scopeType: ScopeType = activeTab === 'roles' ? 'role' : 'member'

    // Highlight the row whose detail is open in the side panel
    const openInPanelId =
        sidePanelOpen && selectedTab === SidePanelTab.AccessDetail && activePanelSubject?.scopeType === scopeType
            ? activePanelSubject.subjectId
            : null

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
                                visibleResources={visibleResourceKeySet}
                                filteredResources={filteredResourceKeySet}
                                selectedEntryId={openInPanelId}
                                onEdit={(entry) => {
                                    if (!accessDetailPanelEnabled) {
                                        openRuleModal({ scopeType, entry, projectId })
                                        return
                                    }
                                    openAccessDetailPanel(scopeType, getEntryId(entry))
                                    openSidePanel(SidePanelTab.AccessDetail, `${scopeType}:${getEntryId(entry)}`)
                                }}
                            />
                        </div>
                    )}
                </AccessControlTabContainer>
            </div>

            {ruleModalState && <GroupedAccessControlRuleModal state={ruleModalState} />}
        </>
    )
}

function AccessControlTabContainer(props: { activeTab: AccessControlsTab; children?: React.ReactNode }): JSX.Element {
    if (props.activeTab === 'roles') {
        return (
            <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS} featureDetail="resource-access-controls-roles">
                <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="access-control-roles">
                    {props.children}
                </PayGateMini>
            </PayGateMini>
        )
    }
    if (props.activeTab === 'members') {
        return (
            <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="access-control-members">
                {props.children}
            </PayGateMini>
        )
    }

    return <>{props.children}</>
}

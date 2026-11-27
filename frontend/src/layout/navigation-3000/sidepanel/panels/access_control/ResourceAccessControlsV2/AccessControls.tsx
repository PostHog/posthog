import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { AccessControlDefaultSettings } from './AccessControlDefaultSettings'
import { AccessControlFilters } from './AccessControlFilters'
import { accessControlsLogic } from './accessControlsLogic'
import { AccessControlTabContainer } from './AccessControlTabContainer'
import { AccessControlTable } from './AccessControlTable'
import { GroupedAccessControlRuleModal } from './GroupedAccessControlRuleModal'
import { getEntryId } from './helpers'
import { QuillAccessControls } from './QuillAccessControls'
import type { AccessControlSettingsEntry, AccessControlsTab, ScopeType } from './types'

export function AccessControls({
    projectId,
    tabsRightSlot,
}: {
    projectId: string
    tabsRightSlot?: React.ReactNode
}): JSX.Element {
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
        terraformDisabledReason,
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
    const quillSurface = useQuillSurface()

    const scopeType: ScopeType = activeTab === 'roles' ? 'role' : 'member'

    // Highlight the row whose detail is open in the side panel
    const openInPanelId =
        sidePanelOpen && selectedTab === SidePanelTab.AccessDetail && activePanelSubject?.scopeType === scopeType
            ? activePanelSubject.subjectId
            : null

    const onEdit = (entry: AccessControlSettingsEntry): void => {
        if (!accessDetailPanelEnabled) {
            openRuleModal({ scopeType, entry, projectId })
            return
        }
        openAccessDetailPanel(scopeType, getEntryId(entry))
        openSidePanel(SidePanelTab.AccessDetail, `${scopeType}:${getEntryId(entry)}`)
    }

    if (quillSurface) {
        return (
            <QuillAccessControls
                projectId={projectId}
                tabsRightSlot={tabsRightSlot}
                selectedEntryId={openInPanelId}
                onEdit={onEdit}
            />
        )
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
                    rightSlot={tabsRightSlot}
                    rightSlotClassName="pr-0"
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
                                cannotEditReason={terraformDisabledReason}
                                visibleResources={visibleResourceKeySet}
                                filteredResources={filteredResourceKeySet}
                                selectedEntryId={openInPanelId}
                                onEdit={onEdit}
                            />
                        </div>
                    )}
                </AccessControlTabContainer>
            </div>

            {ruleModalState && <GroupedAccessControlRuleModal state={ruleModalState} />}
        </>
    )
}

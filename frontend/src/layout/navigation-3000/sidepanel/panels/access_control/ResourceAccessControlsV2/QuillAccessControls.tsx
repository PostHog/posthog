import { useActions, useValues } from 'kea'

import { Tabs, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { accessControlsLogic } from './accessControlsLogic'
import { AccessControlTabContainer } from './AccessControlTabContainer'
import { QuillAccessControlDefaultSettings } from './QuillAccessControlDefaultSettings'
import { QuillAccessControlFilters } from './QuillAccessControlFilters'
import { QuillAccessControlTable } from './QuillAccessControlTable'
import { QuillGroupedAccessControlRuleModal } from './QuillGroupedAccessControlRuleModal'
import type { AccessControlSettingsEntry, AccessControlsTab } from './types'

export function QuillAccessControls({
    projectId,
    tabsRightSlot,
    selectedEntryId,
    onEdit,
}: {
    projectId: string
    tabsRightSlot?: React.ReactNode
    /** Entry whose detail is currently open, highlighted in the list */
    selectedEntryId: string | null
    onEdit: (entry: AccessControlSettingsEntry) => void
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
        visibleResourceKeySet,
        filteredResourceKeySet,
        ruleModalState,
    } = useValues(logic)

    const { setActiveTab, setSearchText, setFilters } = useActions(logic)

    return (
        <>
            <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as AccessControlsTab)}>
                        <TabsList variant="line">
                            <TabsTrigger value="defaults">Defaults</TabsTrigger>
                            {canUseRoles ? (
                                <TabsTrigger value="roles">Roles</TabsTrigger>
                            ) : (
                                <Tooltip>
                                    <TooltipTrigger render={<TabsTrigger value="roles" />}>Roles</TooltipTrigger>
                                    <TooltipContent>Requires role-based access</TooltipContent>
                                </Tooltip>
                            )}
                            <TabsTrigger value="members">Members</TabsTrigger>
                        </TabsList>
                    </Tabs>
                    {tabsRightSlot}
                </div>

                <AccessControlTabContainer activeTab={activeTab}>
                    {activeTab === 'defaults' ? (
                        <QuillAccessControlDefaultSettings projectId={projectId} />
                    ) : (
                        <div className="flex flex-col gap-4">
                            <QuillAccessControlFilters
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
                            <QuillAccessControlTable
                                activeTab={activeTab}
                                entries={activeTab === 'roles' ? filteredRoles : filteredMembers}
                                loading={loading}
                                canEditAny={canEdit}
                                cannotEditReason={terraformDisabledReason}
                                visibleResources={visibleResourceKeySet}
                                filteredResources={filteredResourceKeySet}
                                selectedEntryId={selectedEntryId}
                                onEdit={onEdit}
                            />
                        </div>
                    )}
                </AccessControlTabContainer>
            </div>

            {ruleModalState && <QuillGroupedAccessControlRuleModal state={ruleModalState} />}
        </>
    )
}

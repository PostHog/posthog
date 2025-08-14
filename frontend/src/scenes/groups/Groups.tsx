import { useActions, useValues } from 'kea'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { Link } from 'lib/lemon-ui/Link'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { GroupsIntroduction } from 'scenes/groups/GroupsIntroduction'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { Query } from '~/queries/Query/Query'
import { GroupTypeIndex } from '~/types'

import { groupsListLogic } from './groupsListLogic'
import { groupsSceneLogic } from './groupsSceneLogic'
import { QueryContext } from '~/queries/types'
import { getCRMColumns } from './crm/utils'
import { groupViewLogic } from './groupViewLogic'
import { PersonsManagementSceneTabs } from 'scenes/persons-management/PersonsManagementSceneTabs'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'

export function Groups({ groupTypeIndex }: { groupTypeIndex: GroupTypeIndex }): JSX.Element {
    const { groupTypeName, groupTypeNamePlural } = useValues(groupsSceneLogic)
    const { query, queryWasModified } = useValues(groupsListLogic({ groupTypeIndex }))
    const { setQuery } = useActions(groupsListLogic({ groupTypeIndex }))
    const { saveGroupViewModalOpen, groupViewName } = useValues(groupViewLogic)
    const { setSaveGroupViewModalOpen, setGroupViewName, saveGroupView } = useActions(groupViewLogic)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const hasCrmIterationOneEnabled = useFeatureFlag('CRM_ITERATION_ONE')

    if (groupTypeIndex === undefined) {
        throw new Error('groupTypeIndex is undefined')
    }

    if (
        groupsAccessStatus == GroupsAccessStatus.HasAccess ||
        groupsAccessStatus == GroupsAccessStatus.HasGroupTypes ||
        groupsAccessStatus == GroupsAccessStatus.NoAccess
    ) {
        return (
            <>
                <PersonsManagementSceneTabs tabKey={`groups-${groupTypeIndex}`} />
                <GroupsIntroduction />
            </>
        )
    }

    let columns = {
        group_name: {
            title: groupTypeName,
        },
    } as QueryContext['columns']
    let hiddenColumns = [] as string[]
    if (hasCrmIterationOneEnabled) {
        columns = getCRMColumns(groupTypeName, groupTypeIndex)
        hiddenColumns.push('key')
    }

    return (
        <>
            <PersonsManagementSceneTabs
                tabKey={`groups-${groupTypeIndex}`}
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr={`new-group-${groupTypeIndex}`}
                        onClick={() => router.actions.push(urls.group(groupTypeIndex, 'new', false))}
                    >
                        New {aggregationLabel(groupTypeIndex).singular}
                    </LemonButton>
                }
            />
            <Query
                query={{ ...query, hiddenColumns }}
                setQuery={setQuery}
                context={{
                    refresh: 'blocking',
                    emptyStateHeading: queryWasModified
                        ? `No ${groupTypeNamePlural} found`
                        : `No ${groupTypeNamePlural} exist because none have been identified`,
                    emptyStateDetail: queryWasModified ? (
                        'Try changing the date range or property filters.'
                    ) : (
                        <>
                            Go to the{' '}
                            <Link to="https://posthog.com/docs/product-analytics/group-analytics#how-to-create-groups">
                                group analytics docs
                            </Link>{' '}
                            to learn what needs to be done
                        </>
                    ),
                    columns,
                    groupTypeLabel: groupTypeNamePlural,
                }}
                dataAttr="groups-table"
            />

            {hasCrmIterationOneEnabled && (
                <LemonModal
                    isOpen={saveGroupViewModalOpen}
                    onClose={() => setSaveGroupViewModalOpen(false)}
                    title="Save filtered groups view"
                    footer={
                        <>
                            <LemonButton onClick={() => setSaveGroupViewModalOpen(false)}>Cancel</LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => saveGroupView(window.location.href, groupTypeIndex)}
                                disabledReason={!groupViewName.trim() ? 'Name is required' : undefined}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                >
                    <div className="space-y-4">
                        <p>Save this filtered view as a shortcut in the People panel.</p>
                        <LemonInput
                            placeholder="Enter view name"
                            value={groupViewName}
                            onChange={setGroupViewName}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && groupViewName.trim()) {
                                    saveGroupView(window.location.href, groupTypeIndex)
                                }
                            }}
                            autoFocus
                        />
                    </div>
                </LemonModal>
            )}
        </>
    )
}

export function GroupsScene(): JSX.Element {
    const { groupTypeIndex } = useValues(groupsSceneLogic)
    return <Groups groupTypeIndex={groupTypeIndex as GroupTypeIndex} />
}

export const scene: SceneExport = {
    component: GroupsScene,
    logic: groupsSceneLogic,
    settingSectionId: 'environment-crm',
}

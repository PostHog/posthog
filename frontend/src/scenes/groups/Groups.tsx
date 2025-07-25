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

export function Groups({ groupTypeIndex }: { groupTypeIndex: GroupTypeIndex }): JSX.Element {
    const { groupTypeName, groupTypeNamePlural } = useValues(groupsSceneLogic)
    const { query, queryWasModified, saveFiltersModalOpen, filterShortcutName } = useValues(
        groupsListLogic({ groupTypeIndex })
    )
    const { setQuery, setSaveFiltersModalOpen, setFilterShortcutName, saveFilterAsShortcut } = useActions(
        groupsListLogic({ groupTypeIndex })
    )
    const { groupsAccessStatus } = useValues(groupsAccessLogic)
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
                    isOpen={saveFiltersModalOpen}
                    onClose={() => setSaveFiltersModalOpen(false)}
                    title="Save filtered groups view"
                    footer={
                        <>
                            <LemonButton onClick={() => setSaveFiltersModalOpen(false)}>Cancel</LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => saveFilterAsShortcut(window.location.href)}
                                disabledReason={!filterShortcutName.trim() ? 'Name is required' : undefined}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                >
                    <div className="space-y-4">
                        <p>Save this filtered view as a shortcut in the People panel.</p>
                        <LemonInput
                            placeholder="Enter shortcut name"
                            value={filterShortcutName}
                            onChange={setFilterShortcutName}
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
}

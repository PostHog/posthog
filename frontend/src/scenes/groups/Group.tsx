import { useActions, useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { groupLogic } from 'scenes/groups/groupLogic'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { SceneExport } from 'scenes/sceneTypes'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { Group as IGroup, PersonsTabType, PropertyDefinitionType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { RelatedFeatureFlags } from 'scenes/persons/RelatedFeatureFlags'
import { Query } from '~/queries/Query/Query'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

export const scene: SceneExport = {
    component: Group,
    logic: groupLogic,
}

function GroupCaption({ groupData, groupTypeName }: { groupData: IGroup; groupTypeName: string }): JSX.Element {
    return (
        <div className="flex items-center flex-wrap">
            <div className="mr-4">
                <span className="text-muted">Type:</span> {groupTypeName}
            </div>
            <div className="mr-4">
                <span className="text-muted">Key:</span>{' '}
                <CopyToClipboardInline
                    tooltipMessage={null}
                    description="group key"
                    style={{ display: 'inline-flex', justifyContent: 'flex-end' }}
                >
                    {groupData.group_key}
                </CopyToClipboardInline>
            </div>
            <div>
                <span className="text-muted">First seen:</span>{' '}
                {groupData.created_at ? <TZLabel time={groupData.created_at} /> : 'unknown'}
            </div>
        </div>
    )
}

export function Group(): JSX.Element {
    const {
        groupData,
        groupDataLoading,
        groupTypeName,
        groupKey,
        groupTypeIndex,
        groupType,
        groupTab,
        groupEventsQuery,
    } = useValues(groupLogic)
    const { setGroupTab, setGroupEventsQuery } = useActions(groupLogic)

    if (!groupData) {
        return groupDataLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="group" />
    }

    return (
        <>
            <PageHeader
                title={groupDisplayId(groupData.group_key, groupData.group_properties)}
                caption={<GroupCaption groupData={groupData} groupTypeName={groupTypeName} />}
            />
            <LemonTabs
                activeKey={groupTab ?? PersonsTabType.PROPERTIES}
                onChange={(tab) => setGroupTab(tab)}
                tabs={[
                    {
                        key: PersonsTabType.PROPERTIES,
                        label: <span data-attr="persons-properties-tab">Properties</span>,
                        content: (
                            <PropertiesTable
                                type={PropertyDefinitionType.Group}
                                properties={groupData.group_properties || {}}
                                embedded={false}
                                searchable
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.EVENTS,
                        label: <span data-attr="persons-events-tab">Events</span>,
                        content: groupEventsQuery ? (
                            <Query query={groupEventsQuery} setQuery={setGroupEventsQuery} />
                        ) : (
                            <Spinner />
                        ),
                    },
                    {
                        key: PersonsTabType.RELATED,
                        label: (
                            <div className="flex items-center" data-attr="group-related-tab">
                                Related people & groups
                            </div>
                        ),
                        tooltip: `People and groups that have shared events with this ${groupTypeName} in the last 90 days.`,
                        content: <RelatedGroups id={groupKey} groupTypeIndex={groupTypeIndex} />,
                    },
                    {
                        key: PersonsTabType.FEATURE_FLAGS,
                        label: <span data-attr="groups-related-flags-tab">Feature flags</span>,
                        content: (
                            <RelatedFeatureFlags distinctId={groupData.group_key} groups={{ [groupType]: groupKey }} />
                        ),
                    },
                ]}
            />
        </>
    )
}

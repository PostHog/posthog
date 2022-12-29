import { Tabs } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { groupLogic } from 'scenes/groups/groupLogic'
import { EventsTable } from 'scenes/events/EventsTable'
import { urls } from 'scenes/urls'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { Tooltip } from 'lib/components/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { Group as IGroup, PersonsTabType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { RelatedFeatureFlags } from 'scenes/persons/RelatedFeatureFlags'
import { Query } from '~/queries/Query/Query'
import { FEATURE_FLAGS } from 'lib/constants'
import { NodeKind } from '~/queries/schema'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'

const { TabPane } = Tabs

export const scene: SceneExport = {
    component: Group,
    logic: groupLogic,
}

function GroupCaption({ groupData, groupTypeName }: { groupData: IGroup; groupTypeName: string }): JSX.Element {
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap' }}>
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
    const { groupData, groupDataLoading, groupTypeName, groupKey, groupTypeIndex, groupType } = useValues(groupLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]

    if (!groupData) {
        return groupDataLoading ? <SpinnerOverlay /> : <NotFound object="group" />
    }

    return (
        <>
            <PageHeader
                title={groupDisplayId(groupData.group_key, groupData.group_properties)}
                caption={<GroupCaption groupData={groupData} groupTypeName={groupTypeName} />}
            />

            <Tabs>
                <TabPane
                    tab={<span data-attr="persons-properties-tab">Properties</span>}
                    key={PersonsTabType.PROPERTIES}
                >
                    <PropertiesTable properties={groupData.group_properties || {}} embedded={false} searchable />
                </TabPane>
                <TabPane tab={<span data-attr="persons-events-tab">Events</span>} key={PersonsTabType.EVENTS}>
                    {featureDataExploration ? (
                        <Query
                            query={{
                                kind: NodeKind.DataTableNode,
                                full: true,
                                source: {
                                    kind: NodeKind.EventsQuery,
                                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                                    fixedProperties: [{ key: `$group_${groupTypeIndex}`, value: groupKey }],
                                },
                            }}
                        />
                    ) : (
                        <EventsTable
                            pageKey={`${groupTypeIndex}::${groupKey}`}
                            fixedFilters={{
                                properties: [{ key: `$group_${groupTypeIndex}`, value: groupKey }],
                            }}
                            sceneUrl={urls.group(groupTypeIndex.toString(), groupKey)}
                            showCustomizeColumns={false}
                        />
                    )}
                </TabPane>

                <TabPane
                    tab={
                        <span data-attr="group-related-tab">
                            Related people & groups
                            <Tooltip
                                title={`People and groups that have shared events with this ${groupTypeName} in the last 90 days.`}
                            >
                                <InfoCircleOutlined style={{ marginLeft: 6, marginRight: 0 }} />
                            </Tooltip>
                        </span>
                    }
                    key={PersonsTabType.RELATED}
                >
                    <RelatedGroups id={groupKey} groupTypeIndex={groupTypeIndex} />
                </TabPane>
                <TabPane
                    tab={<span data-attr="groups-related-flags-tab">Feature flags</span>}
                    key={PersonsTabType.FEATURE_FLAGS}
                >
                    <RelatedFeatureFlags distinctId={groupData.group_key} groups={{ [groupType]: groupKey }} />
                </TabPane>
            </Tabs>
        </>
    )
}

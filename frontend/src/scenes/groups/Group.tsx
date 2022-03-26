import React from 'react'
import { Tabs } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { groupLogic } from 'scenes/groups/groupLogic'
import { EventsTable } from 'scenes/events/EventsTable'
import { urls } from 'scenes/urls'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { Tooltip } from 'lib/components/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { groupDisplayId } from 'scenes/persons/GroupActorHeader'
import { Group as IGroup, PersonsTabType } from '~/types'
import { Loading } from 'lib/utils'
import { PageHeader } from 'lib/components/PageHeader'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

const { TabPane } = Tabs

export const scene: SceneExport = {
    component: Group,
    logic: groupLogic,
}

function GroupCaption({ groupData, groupTypeName }: { groupData: IGroup; groupTypeName: string }): JSX.Element {
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap' }}>
            <div className="mr">
                <span className="text-muted">Type:</span> {groupTypeName}
            </div>
            <div className="mr">
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
    const { groupData, groupDataLoading, groupTypeName, groupKey, groupTypeIndex } = useValues(groupLogic)

    if (!groupData) {
        return groupDataLoading ? <Loading /> : <PageHeader title="Group not found" />
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
                    <EventsTable
                        pageKey={`${groupTypeIndex}::${groupKey}`}
                        fixedFilters={{
                            properties: [{ key: `$group_${groupTypeIndex}`, value: groupKey }],
                        }}
                        sceneUrl={urls.group(groupTypeIndex.toString(), groupKey)}
                        showCustomizeColumns={false}
                    />
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
            </Tabs>
        </>
    )
}

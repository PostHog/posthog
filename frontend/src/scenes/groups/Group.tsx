import React, { useState } from 'react'
import { Row, Tabs, Col, Card, Skeleton } from 'antd'
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

const { TabPane } = Tabs

export const scene: SceneExport = {
    component: Group,
    logic: groupLogic,
}

export function Group(): JSX.Element {
    const { groupData, groupDataLoading, groupTypeName, groupKey, groupTypeIndex } = useValues(groupLogic)

    const [activeCardTab, setActiveCardTab] = useState('properties')

    return (
        <>
            <div style={{ paddingTop: 32 }}>
                <Row gutter={16}>
                    <Col span={16}>
                        {groupData && (
                            <EventsTable
                                pageKey={`${groupTypeIndex}::${groupKey}`}
                                fixedFilters={{
                                    properties: [{ key: `$group_${groupTypeIndex}`, value: groupKey }],
                                }}
                                sceneUrl={urls.group(groupTypeIndex.toString(), groupKey)}
                            />
                        )}
                    </Col>
                    <Col span={8}>
                        <Card className="card-elevated person-detail">
                            {groupData && (
                                <>
                                    <div className="person-header">
                                        <span className="ph-no-capture text-ellipsis">{groupData.group_key}</span>
                                    </div>
                                    <div className="item-group">
                                        <label>Group type</label>
                                        <div>{groupTypeName}</div>
                                    </div>
                                    <div className="item-group">
                                        <label>First seen</label>
                                        <div>{<TZLabel time={groupData.created_at} />}</div>
                                    </div>
                                </>
                            )}
                            {groupDataLoading && <Skeleton paragraph={{ rows: 4 }} active />}
                        </Card>
                        <Card className="card-elevated person-properties" style={{ marginTop: 16 }}>
                            <Tabs
                                defaultActiveKey={activeCardTab}
                                onChange={(tab) => {
                                    setActiveCardTab(tab)
                                }}
                            >
                                <TabPane
                                    tab={<span data-attr="group-properties-tab">Properties</span>}
                                    key="properties"
                                    disabled={groupDataLoading}
                                />
                                <TabPane
                                    tab={
                                        <span data-attr="group-related-tab">
                                            Related people & groups
                                            <Tooltip
                                                title={`Shows people and groups which have shared events with this ${groupTypeName} in the last 90 days.`}
                                            >
                                                <InfoCircleOutlined style={{ marginLeft: 4 }} />
                                            </Tooltip>
                                        </span>
                                    }
                                    key="related"
                                    disabled={groupDataLoading}
                                />
                            </Tabs>
                            {groupData &&
                                (activeCardTab == 'properties' ? (
                                    <div style={{ maxWidth: '100%', overflow: 'hidden' }}>
                                        <h3 className="l3">Properties list</h3>
                                        <PropertiesTable
                                            properties={groupData.group_properties}
                                            className="persons-page-props-table"
                                        />
                                    </div>
                                ) : (
                                    <RelatedGroups id={groupKey} groupTypeIndex={groupTypeIndex} />
                                ))}
                            {groupDataLoading && <Skeleton paragraph={{ rows: 6 }} active />}
                        </Card>
                    </Col>
                </Row>
            </div>
        </>
    )
}

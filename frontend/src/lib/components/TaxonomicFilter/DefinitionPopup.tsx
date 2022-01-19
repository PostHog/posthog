import React from 'react'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Col, Divider, Row } from 'antd'
import { ActionType, CohortType, EventDefinition, PropertyDefinition } from '~/types'
import { ObjectTags } from 'lib/components/ObjectTags'

const taxonomyToTitleMap = {
    [TaxonomicFilterGroupType.Actions]: 'Actions',
    [TaxonomicFilterGroupType.Elements]: 'Elements',
    [TaxonomicFilterGroupType.Events]: 'Events',
    [TaxonomicFilterGroupType.EventProperties]: 'Event Properties',
    [TaxonomicFilterGroupType.PersonProperties]: 'Person Properties',
}

interface DefinitionPopupProps {
    item: EventDefinition | PropertyDefinition | CohortType | ActionType
    type: TaxonomicFilterGroupType
    group: TaxonomicFilterGroup
    onItemEnter?: () => void
}

export function DefinitionPopup({ item, type, group }: DefinitionPopupProps): React.ReactNode {
    const value = group.getValue(item)

    if (!value || !taxonomyToTitleMap[type]) {
        return null
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
            <Row justify="space-between">
                <Col>{taxonomyToTitleMap[type] ?? 'Definitions'}</Col>
                <Col>View details</Col>
            </Row>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
                <Row>{item.name ?? ''}</Row>
                {'description' in item && <Row>{item.description}</Row>}
                {'tags' in item && (
                    <Row>
                        <ObjectTags tags={item.tags ?? []} />
                    </Row>
                )}
            </div>
            <Divider />
            <div style={{ display: 'flex', flexDirection: 'column' }}>
                <Row>Sent as</Row>
                <Row>{item.id}</Row>
            </div>
            <Divider />
            <div style={{ display: 'flex', flexDirection: 'column' }}>
                <Row gutter={16}>
                    {/*<Col className="gutter-row" span={12}>*/}
                    {/*    <Row>First seen</Row>*/}
                    {/*    <Row>{item?.created_at}</Row>*/}
                    {/*</Col>*/}
                    {/*<Col className="gutter-row" span={12}>*/}
                    {/*    <Row>Last seen</Row>*/}
                    {/*    <Row></Row>*/}
                    {/*</Col>*/}
                    {/*<Col className="gutter-row" span={12}>*/}
                    {/*    <Row>Last modified</Row>*/}
                    {/*    <Row></Row>*/}
                    {/*</Col>*/}
                </Row>
            </div>
        </div>
    )
}

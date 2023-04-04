import { useState } from 'react'
import { Row } from 'antd'
import { useActions, useValues } from 'kea'
import { EllipsisOutlined } from '@ant-design/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

export const EventCorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { excludeEventPropertyFromProject, excludeEventFromProject, setFunnelCorrelationDetails } = useActions(logic)
    const { isEventPropertyExcluded, isEventExcluded } = useValues(logic)
    const components = record.event.event.split('::')

    const buttons: LemonButtonProps[] = [
        ...(record.result_type === FunnelCorrelationResultsType.Events
            ? [
                  {
                      children: 'View correlation details',
                      onClick: () => setFunnelCorrelationDetails(record),
                  },
              ]
            : []),
        {
            children: 'Exclude event from project',
            title: 'Remove this event from any correlation analysis report in this project.',
            onClick: () => {
                record.result_type === FunnelCorrelationResultsType.EventWithProperties
                    ? excludeEventPropertyFromProject(components[0], components[1])
                    : excludeEventFromProject(components[0])
            },
            disabled:
                record.result_type === FunnelCorrelationResultsType.EventWithProperties
                    ? isEventPropertyExcluded(components[1])
                    : isEventExcluded(components[0]),
        },
    ]

    return <CorrelationActionsCellComponent buttons={buttons} />
}

export const PropertyCorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { excludePropertyFromProject, setFunnelCorrelationDetails } = useActions(logic)
    const { isPropertyExcludedFromProject } = useValues(logic)
    const propertyName = (record.event.event || '').split('::')[0]

    const buttons: LemonButtonProps[] = [
        {
            children: 'View correlation details',
            onClick: () => setFunnelCorrelationDetails(record),
        },
        {
            children: 'Exclude property from project',
            title: 'Remove this property from any correlation analysis report in this project.',
            onClick: () => excludePropertyFromProject(propertyName),
            disabled: isPropertyExcludedFromProject(propertyName),
        },
    ]

    return <CorrelationActionsCellComponent buttons={buttons} />
}

type CorrelationActionsCellComponentProps = {
    buttons: LemonButtonProps[]
}

const CorrelationActionsCellComponent = ({ buttons }: CorrelationActionsCellComponentProps): JSX.Element => {
    const [popoverOpen, setPopoverOpen] = useState(false)
    return (
        <Row style={{ justifyContent: 'flex-end' }}>
            <Popover
                visible={popoverOpen}
                actionable
                onClickOutside={() => setPopoverOpen(false)}
                overlay={buttons.map((props, index) => (
                    <LemonButton key={index} status="stealth" fullWidth {...props} />
                ))}
            >
                <LemonButton status="stealth" onClick={() => setPopoverOpen(!popoverOpen)}>
                    <EllipsisOutlined className="insight-dropdown-actions" />
                </LemonButton>
            </Popover>
        </Row>
    )
}

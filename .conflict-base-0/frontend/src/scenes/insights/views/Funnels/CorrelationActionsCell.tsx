import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { funnelCorrelationDetailsLogic } from 'scenes/funnels/funnelCorrelationDetailsLogic'
import { funnelCorrelationLogic } from 'scenes/funnels/funnelCorrelationLogic'
import { funnelPropertyCorrelationLogic } from 'scenes/funnels/funnelPropertyCorrelationLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelCorrelation, FunnelCorrelationResultsType } from '~/types'

type CorrelationActionsCellComponentButtonProps = Pick<LemonButtonProps, 'onClick' | 'children' | 'title' | 'disabled'>

type CorrelationActionsCellComponentProps = {
    buttons: CorrelationActionsCellComponentButtonProps[]
}

export const EventCorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { isEventExcluded, isEventPropertyExcluded } = useValues(funnelCorrelationLogic(insightProps))
    const { excludeEventFromProject, excludeEventPropertyFromProject } = useActions(
        funnelCorrelationLogic(insightProps)
    )
    const { openCorrelationDetailsModal } = useActions(funnelCorrelationDetailsLogic(insightProps))
    const components = record.event.event.split('::')

    const buttons: CorrelationActionsCellComponentButtonProps[] = [
        ...(record.result_type === FunnelCorrelationResultsType.Events
            ? [
                  {
                      children: 'View correlation details',
                      onClick: () => openCorrelationDetailsModal(record),
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
    const { isPropertyExcludedFromProject } = useValues(funnelPropertyCorrelationLogic(insightProps))
    const { excludePropertyFromProject } = useActions(funnelPropertyCorrelationLogic(insightProps))
    const { openCorrelationDetailsModal } = useActions(funnelCorrelationDetailsLogic(insightProps))
    const propertyName = (record.event.event || '').split('::')[0]

    const buttons: CorrelationActionsCellComponentButtonProps[] = [
        {
            children: 'View correlation details',
            onClick: () => openCorrelationDetailsModal(record),
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

const CorrelationActionsCellComponent = ({ buttons }: CorrelationActionsCellComponentProps): JSX.Element => {
    const [popoverOpen, setPopoverOpen] = useState(false)
    return (
        <Popover
            visible={popoverOpen}
            actionable
            onClickOutside={() => setPopoverOpen(false)}
            overlay={buttons.map(({ onClick, ...props }, index) => (
                <LemonButton
                    key={index}
                    fullWidth
                    onClick={(e) => {
                        setPopoverOpen(false)
                        onClick && onClick(e)
                    }}
                    {...props}
                />
            ))}
        >
            <LemonButton icon={<IconEllipsis />} onClick={() => setPopoverOpen(!popoverOpen)} />
        </Popover>
    )
}

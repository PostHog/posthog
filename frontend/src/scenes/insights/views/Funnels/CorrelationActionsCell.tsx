import { useState } from 'react'
import { Row } from 'antd'
import { useActions, useValues } from 'kea'
import { EllipsisOutlined } from '@ant-design/icons'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { funnelCorrelationLogic } from 'scenes/funnels/funnelCorrelationLogic'

export const CorrelationActionsCell = ({ record }: { record: FunnelCorrelation }): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { isEventPropertyExcluded } = useValues(funnelLogic(insightProps))
    const { excludeEventPropertyFromProject, setFunnelCorrelationDetails } = useActions(funnelLogic(insightProps))
    const { isEventExcluded } = useValues(funnelCorrelationLogic(insightProps))
    const { excludeEventFromProject } = useActions(funnelCorrelationLogic(insightProps))

    const components = record.event.event.split('::')
    const [popoverOpen, setPopoverOpen] = useState(false)

    return (
        <Row style={{ justifyContent: 'flex-end' }}>
            <Popover
                visible={popoverOpen}
                actionable
                onClickOutside={() => setPopoverOpen(false)}
                overlay={
                    <>
                        {record.result_type === FunnelCorrelationResultsType.Events && (
                            <LemonButton onClick={() => setFunnelCorrelationDetails(record)} fullWidth status="stealth">
                                View correlation details
                            </LemonButton>
                        )}
                        <LemonButton
                            disabled={
                                record.result_type === FunnelCorrelationResultsType.EventWithProperties
                                    ? isEventPropertyExcluded(components[1])
                                    : isEventExcluded(components[0])
                            }
                            onClick={() =>
                                record.result_type === FunnelCorrelationResultsType.EventWithProperties
                                    ? excludeEventPropertyFromProject(components[0], components[1])
                                    : excludeEventFromProject(components[0])
                            }
                            fullWidth
                            title="Remove this event from any correlation analysis report in this project."
                            status="stealth"
                        >
                            Exclude event from project
                        </LemonButton>
                    </>
                }
            >
                <LemonButton status="stealth" onClick={() => setPopoverOpen(!popoverOpen)}>
                    <EllipsisOutlined className="insight-dropdown-actions" />
                </LemonButton>
            </Popover>
        </Row>
    )
}

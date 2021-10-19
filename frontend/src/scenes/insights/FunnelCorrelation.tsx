import { Card } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from './insightLogic'
import './FunnelCorrelation.scss'
import { FunnelCorrelationTable } from './InsightTabs/FunnelTab/FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './InsightTabs/FunnelTab/FunnelPropertyCorrelationTable'
import { IconFeedbackWarning } from 'lib/components/icons'
import { CloseOutlined } from '@ant-design/icons'

export const FunnelCorrelation = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed, stepsWithCount } = useValues(funnelLogic(insightProps))
    const { hideSkewWarning } = useActions(funnelLogic(insightProps))

    if (stepsWithCount.length <= 1) {
        return null
    }

    return (
        <div className="funnel-correlation">
            {isSkewed && (
                <Card className="skew-warning">
                    <h4>
                        <IconFeedbackWarning style={{ fontSize: 24, marginRight: 4, color: 'var(--warning)' }} /> Adjust
                        your funnel definition to improve correlation analysis
                        <CloseOutlined className="close-button" onClick={hideSkewWarning} />
                    </h4>
                    <div>
                        <b>Tips for adjusting your funnel:</b>
                        <ol>
                            <li>
                                Adjust your first funnel step to be more specific. For example, choose a page or an
                                event that occurs less frequently.
                            </li>
                            <li>Choose an event that happens more frequently for subsequent funnels steps.</li>
                        </ol>
                    </div>
                </Card>
            )}

            <FunnelCorrelationTable />
            <FunnelPropertyCorrelationTable />
        </div>
    )
}

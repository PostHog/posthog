// eslint-disable-next-line no-restricted-imports
import { CloseOutlined } from '@ant-design/icons'
import { Card } from 'antd'
import { useActions, useValues } from 'kea'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export const FunnelCorrelationSkewWarning = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed } = useValues(funnelDataLogic(insightProps))
    const { hideSkewWarning } = useActions(funnelDataLogic(insightProps))

    if (!isSkewed) {
        return null
    }

    return (
        <Card className="skew-warning">
            <h4>
                <IconFeedback style={{ fontSize: 24, marginRight: 4, color: 'var(--warning)' }} /> Adjust your funnel
                definition to improve correlation analysis
                <CloseOutlined className="close-button" onClick={hideSkewWarning} />
            </h4>
            <div>
                <b>Tips for adjusting your funnel:</b>
                <ol>
                    <li>
                        Adjust your first funnel step to be more specific. For example, choose a page or an event that
                        occurs less frequently.
                    </li>
                    <li>Choose an event that happens more frequently for subsequent funnels steps.</li>
                </ol>
            </div>
        </Card>
    )
}

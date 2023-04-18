import { useActions, useValues } from 'kea'
import { Card } from 'antd'

import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

import { IconFeedbackWarning } from 'lib/lemon-ui/icons'
import { CloseOutlined } from '@ant-design/icons'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

export const FunnelCorrelationSkewWarningDataExploration = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed } = useValues(funnelDataLogic(insightProps))
    const { hideSkewWarning } = useActions(funnelDataLogic(insightProps))

    return <FunnelCorrelationSkewWarningComponent isSkewed={isSkewed} hideSkewWarning={hideSkewWarning} />
}

export const FunnelCorrelationSkewWarning = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed } = useValues(funnelLogic(insightProps))
    const { hideSkewWarning } = useActions(funnelLogic(insightProps))

    return <FunnelCorrelationSkewWarningComponent isSkewed={isSkewed} hideSkewWarning={hideSkewWarning} />
}

type FunnelCorrelationSkewWarningComponentProps = {
    isSkewed: boolean
    hideSkewWarning: () => void
}

const FunnelCorrelationSkewWarningComponent = ({
    isSkewed,
    hideSkewWarning,
}: FunnelCorrelationSkewWarningComponentProps): JSX.Element | null => {
    if (!isSkewed) {
        return null
    }

    return (
        <Card className="skew-warning">
            <h4>
                <IconFeedbackWarning style={{ fontSize: 24, marginRight: 4, color: 'var(--warning)' }} /> Adjust your
                funnel definition to improve correlation analysis
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

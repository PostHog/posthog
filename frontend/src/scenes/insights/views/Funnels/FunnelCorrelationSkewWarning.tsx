import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
        <div className="skew-warning">
            <h4>
                <div className="flex items-center deprecated-space-x-1">
                    <IconFeedback style={{ fontSize: 24, marginRight: 4, color: 'var(--warning)' }} />
                    <span>Adjust your funnel definition to improve correlation analysis</span>
                </div>
                <LemonButton icon={<IconX />} onClick={hideSkewWarning} />
            </h4>
            <div className="px-2">
                <b className="font-medium">Tips for adjusting your funnel:</b>
                <ol>
                    <li>
                        Adjust your first funnel step to be more specific. For example, choose a page or an event that
                        occurs less frequently.
                    </li>
                    <li>Choose an event that happens more frequently for subsequent funnels steps.</li>
                </ol>
            </div>
        </div>
    )
}

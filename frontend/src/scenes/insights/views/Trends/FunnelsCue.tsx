import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelsCueLogic } from 'scenes/insights/views/Trends/funnelsCueLogic'

export function FunnelsCue(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { shown } = useValues(funnelsCueLogic(insightProps))
    const { optOut, displayAsFunnel } = useActions(funnelsCueLogic(insightProps))

    if (!shown) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            action={{
                onClick: displayAsFunnel,
                children: 'Try this insight as a funnel',
            }}
            onClose={() => optOut(true)}
            className="mb-4"
        >
            Looks like you have multiple events. A funnel can help better visualize your user’s progression across each
            event.
        </LemonBanner>
    )
}

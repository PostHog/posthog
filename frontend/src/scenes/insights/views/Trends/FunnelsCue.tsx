import { useActions, useValues } from 'kea'
import { funnelsCueLogic } from 'scenes/insights/views/Trends/funnelsCueLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { InsightType } from '~/types'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'

export function FunnelsCue(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { optOut } = useActions(funnelsCueLogic(insightProps))
    const { shown } = useValues(funnelsCueLogic(insightProps))

    if (!shown) {
        return null
    }

    return (
        <AlertMessage
            type="info"
            action={{
                to: urls.insightNew({ insight: InsightType.FUNNELS }),
                status: 'primary',
                children: 'Try this insight as a funnel',
            }}
            onClose={() => optOut(true)}
            className="mb-4"
        >
            Looks like you have multiple events. A funnel can help better visualize your user’s progression across each
            event.
        </AlertMessage>
    )
}

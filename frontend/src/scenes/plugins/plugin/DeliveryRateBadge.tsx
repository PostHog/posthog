import { Badge } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { urls } from 'scenes/urls'
import { Link } from 'lib/components/Link'

type BadgeColor = 'green' | 'yellow' | 'red' | 'grey'

export function DeliveryRateBadge({
    deliveryRate,
    pluginConfigId,
}: {
    deliveryRate: number | null
    pluginConfigId: number
}): JSX.Element {
    const [color, tooltip] = deliveryRateSummary(deliveryRate)
    return (
        <Tooltip title={tooltip}>
            <Link to={urls.appMetrics(pluginConfigId)}>
                <Badge color={color} />
            </Link>
        </Tooltip>
    )
}

function deliveryRateSummary(deliveryRate: number | null): [BadgeColor, string] {
    if (deliveryRate === null) {
        return ['grey', 'No events processed by this app in the past 24 hours']
    } else {
        let color: BadgeColor = 'red'
        if (deliveryRate >= 0.99) {
            color = 'green'
        } else if (deliveryRate >= 0.75) {
            color = 'yellow'
        }
        return [color, `Delivery rate for past 24 hours: ${Math.floor(deliveryRate * 1000) / 10}%`]
    }
}

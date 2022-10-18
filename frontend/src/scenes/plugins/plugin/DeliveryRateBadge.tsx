import { Badge } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'

type BadgeColor = 'green' | 'yellow' | 'red' | 'grey'

export function DeliveryRateBadge({ deliveryRate }: { deliveryRate: number | null }): JSX.Element {
    const [color, tooltip] = deliveryRateSummary(deliveryRate)
    return (
        <Tooltip title={tooltip}>
            <Badge color={color} />
        </Tooltip>
    )
}

function deliveryRateSummary(deliveryRate: number | null): [BadgeColor, string] {
    if (deliveryRate === null) {
        return ['grey', 'No events processed by this app in the past day']
    } else {
        let color: BadgeColor = 'red'
        if (deliveryRate >= 0.99) {
            color = 'green'
        } else if (deliveryRate >= 0.75) {
            color = 'yellow'
        }
        return [color, `Delivery rate for past day: ${Math.floor(deliveryRate * 1000) / 10}%`]
    }
}

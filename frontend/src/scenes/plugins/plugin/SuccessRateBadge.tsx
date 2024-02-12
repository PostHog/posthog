import { LemonBadge, LemonBadgeProps } from '@posthog/lemon-ui'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

export function SuccessRateBadge({
    deliveryRate,
    pluginConfigId,
}: {
    deliveryRate: number | null
    pluginConfigId: number
}): JSX.Element {
    const [status, tooltip] = successRateSummary(deliveryRate)
    return (
        <Tooltip title={tooltip}>
            <Link to={urls.appMetrics(pluginConfigId)}>
                <LemonBadge status={status} />
            </Link>
        </Tooltip>
    )
}

function successRateSummary(deliveryRate: number | null): [NonNullable<LemonBadgeProps['status']>, string] {
    if (deliveryRate === null) {
        return ['muted', 'No events processed by this app in the past 24 hours']
    } else {
        let color: NonNullable<LemonBadgeProps['status']>
        if (deliveryRate >= 0.99) {
            color = 'success'
        } else if (deliveryRate >= 0.75) {
            color = 'warning'
        } else {
            color = 'danger'
        }
        return [color, `Success rate for past 24 hours: ${Math.floor(deliveryRate * 1000) / 10}%`]
    }
}

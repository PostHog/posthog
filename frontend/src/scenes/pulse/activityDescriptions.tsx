import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PULSE_ACTIVITY_SCOPE } from './pulseTypes'
import { formatSignedPct } from './utils'

export function pulseActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== PULSE_ACTIVITY_SCOPE) {
        return defaultDescriber(logItem, asNotification)
    }

    const context = logItem.detail?.context as
        | {
              digest_id?: string
              metric_label?: string
              narrative?: string
              change_pct?: number
          }
        | undefined

    if (logItem.activity === 'surfaced' && context) {
        const changePct = context.change_pct ?? 0
        const tone = changePct >= 0 ? 'rose' : 'dropped'
        const pct = formatSignedPct(changePct)
        return {
            description: (
                <>
                    <strong>{context.metric_label || 'A metric'}</strong> {tone} ({pct}) — Pulse surfaced this finding.{' '}
                    <Link to={urls.pulse()}>Open Pulse</Link>
                </>
            ),
            extendedDescription: context.narrative ? <span className="text-muted">{context.narrative}</span> : undefined,
        }
    }

    return defaultDescriber(logItem, asNotification)
}

import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type { TicketPatternApi } from '../../generated/api.schemas'

const SEVERITY_TAG_TYPE: Record<TicketPatternApi['severity'], LemonTagType> = {
    critical: 'danger',
    high: 'caution',
    medium: 'warning',
    low: 'default',
}

export function TicketPatternSeverityTag({ severity }: { severity: TicketPatternApi['severity'] }): JSX.Element {
    return <LemonTag type={SEVERITY_TAG_TYPE[severity]}>{severity}</LemonTag>
}

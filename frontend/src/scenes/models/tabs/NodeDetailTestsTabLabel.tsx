import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

/** Erroring means a check could not run at all, so it reports no failure count to speak of. */
const TONES: Record<string, string> = {
    failing: 'text-danger',
    warn: 'text-warning',
    erroring: 'text-warning',
}

export function NodeDetailTestsTabLabel({ subjectId }: { subjectId: string }): JSX.Element {
    const { health } = useValues(dataQualityChecksLogic({ subjectType: 'view', subjectId }))
    const tone = health ? TONES[health.health] : undefined
    const explanation =
        health?.health === 'erroring'
            ? 'A check could not run'
            : `${pluralize(health?.checks_failing ?? 0, 'check')} failing`

    return (
        <span className="flex items-center gap-1">
            Tests
            {tone && (
                <Tooltip title={explanation}>
                    <IconWarning className={tone} />
                </Tooltip>
            )}
        </span>
    )
}

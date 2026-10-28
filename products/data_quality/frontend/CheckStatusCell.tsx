import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { CHECK_STATUS_TAG_TYPES, failingForLabel } from './checksConstants'
import type { DataQualityCheckApi } from './generated/api.schemas'

/** The status, plus how long it has been broken -- a red tag alone never says "since when". */
export function CheckStatusCell({
    check,
}: {
    check: Pick<DataQualityCheckApi, 'last_status' | 'last_succeeded_at' | 'failing_since'> &
        Partial<Pick<DataQualityCheckApi, 'subject_status'>>
}): JSX.Element {
    if (check.subject_status === 'needs_review') {
        return (
            <Tooltip title="This check was copied from an earlier version. Edit it to match this version's columns before running it.">
                <LemonTag type="warning">Needs review</LemonTag>
            </Tooltip>
        )
    }
    const failingFor = failingForLabel(check)
    if (!check.last_status) {
        return <LemonTag type="muted">Not run yet</LemonTag>
    }
    return (
        <div className="flex items-center gap-1.5">
            <LemonTag type={CHECK_STATUS_TAG_TYPES[check.last_status] ?? 'default'}>{check.last_status}</LemonTag>
            {failingFor && (
                <Tooltip
                    title={
                        check.last_succeeded_at ? `Last passed ${dayjs(check.last_succeeded_at).fromNow()}` : undefined
                    }
                >
                    <span className="text-secondary text-xs whitespace-nowrap">{failingFor}</span>
                </Tooltip>
            )}
        </div>
    )
}

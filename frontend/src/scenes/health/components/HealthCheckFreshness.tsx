import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { healthCheckFreshnessLogic } from '../healthCheckFreshnessLogic'

export interface HealthCheckFreshnessProps {
    kind: string
    /** Called as the re-check lands, so the surface can reload whatever it renders from the issues. */
    onRechecked?: () => void
}

/**
 * When this check last ran, when it runs next, and a way to run it now.
 *
 * A check result on its own reads as a statement about the present, which it is not: checks run on
 * a daily schedule and skip dormant projects, so a finding can outlive the problem it describes.
 */
export function HealthCheckFreshness({ kind, onRechecked }: HealthCheckFreshnessProps): JSX.Element | null {
    const { checkStateByKind, refreshingKinds } = useValues(healthCheckFreshnessLogic)
    const { recheckKinds } = useActions(healthCheckFreshnessLogic)

    const check = checkStateByKind[kind]
    if (!check) {
        return null
    }

    const isRechecking = refreshingKinds.includes(kind)

    return (
        <div className="flex items-center flex-wrap gap-x-2 gap-y-1 text-xs text-muted">
            {check.last_run_at ? (
                <span>
                    Checked <TZLabel time={check.last_run_at} />
                </span>
            ) : (
                <span>Not checked yet</span>
            )}
            {check.stale && (
                <LemonTag type="warning" size="small">
                    Out of date
                </LemonTag>
            )}
            {check.next_run_at && (
                <span>
                    Next check <TZLabel time={check.next_run_at} />
                </span>
            )}
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconRefresh />}
                loading={isRechecking}
                disabledReason={isRechecking ? 'Re-checking' : undefined}
                onClick={(e) => {
                    e.stopPropagation()
                    recheckKinds([kind], onRechecked)
                }}
                tooltip="Run this check again now, without waiting for the next scheduled run"
                data-attr={`health-check-recheck-${kind}`}
            >
                Re-check
            </LemonButton>
        </div>
    )
}

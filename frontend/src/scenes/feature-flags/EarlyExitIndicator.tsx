import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function EarlyExitIndicator(): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 text-xs text-muted">
            <Tooltip title="Condition sets are evaluated in order. The first set whose property filters match decides the result — if that set's rollout percentage excludes the user, the flag returns false and later sets are skipped.">
                <IconInfo className="text-sm" />
            </Tooltip>
            <span>Stops at the first condition set whose property filters match</span>
        </div>
    )
}

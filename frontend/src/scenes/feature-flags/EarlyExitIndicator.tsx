import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function EarlyExitIndicator(): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 text-xs text-muted">
            <Tooltip title="Conditions are evaluated in order — the first matching condition set determines the result and later conditions are skipped.">
                <IconInfo className="text-sm" />
            </Tooltip>
            <span>Stops evaluation at first matching condition set</span>
        </div>
    )
}

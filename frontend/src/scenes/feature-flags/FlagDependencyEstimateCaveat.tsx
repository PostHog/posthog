import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { FLAG_DEPENDENCY_ESTIMATE_TOOLTIP } from './constants'

// Shown in place of the blast-radius count when a condition's only filter is a flag dependency,
// which the estimate can't evaluate and would otherwise count as everyone.
export function FlagDependencyEstimateCaveat({ className }: { className?: string }): JSX.Element {
    return (
        <div className={className}>
            <span>
                Depends on another feature flag, so the match estimate isn't shown.
                <Tooltip title={FLAG_DEPENDENCY_ESTIMATE_TOOLTIP} interactive>
                    <IconInfo className="text-muted text-xs ml-0.5" />
                </Tooltip>
            </span>
        </div>
    )
}

import { Tooltip } from '@posthog/lemon-ui'

import { HogSenseTooltipContent, SeverityIcon, severityColor } from './HogSenseTooltipContent'
import type { Finding } from './types'

export function HogSenseHint({ finding, className }: { finding: Finding; className?: string }): JSX.Element {
    const color = severityColor(finding.severity)

    return (
        <Tooltip title={<HogSenseTooltipContent finding={finding} />} interactive placement="bottom">
            <div
                className={`inline-flex self-start items-center gap-1.5 text-xs ${color} cursor-pointer${className ? ` ${className}` : ''}`}
            >
                <SeverityIcon severity={finding.severity} />
                <span>{finding.summary}</span>
            </div>
        </Tooltip>
    )
}

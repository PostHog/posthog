import { Tooltip } from '@posthog/lemon-ui'

import { HogSenseTooltipContent, SeverityIcon, severityColor } from './HogSenseTooltipContent'
import type { Finding } from './types'

export function HogSenseHint({ finding }: { finding: Finding }): JSX.Element {
    const color = severityColor(finding.severity)

    return (
        <Tooltip title={<HogSenseTooltipContent finding={finding} />} interactive placement="bottom">
            <div className={`inline-flex self-start items-center gap-1.5 text-xs ${color} cursor-pointer`}>
                <SeverityIcon severity={finding.severity} />
                <span>{finding.summary}</span>
            </div>
        </Tooltip>
    )
}

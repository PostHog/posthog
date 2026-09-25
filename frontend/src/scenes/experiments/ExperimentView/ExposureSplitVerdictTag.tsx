import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ExposureSplitVerdict } from './exposureSplitVerdict'

interface ExposureSplitVerdictTagProps {
    verdict: ExposureSplitVerdict
}

/**
 * The chi-squared verdict, compact enough for the collapsed exposures header. Rendered in
 * both directions, so a header showing a 55/45 split also says whether that is expected.
 */
export function ExposureSplitVerdictTag({ verdict }: ExposureSplitVerdictTagProps): JSX.Element {
    const Icon = verdict.isMismatch ? IconWarning : IconCheckCircle
    const tooltip = [verdict.headline, verdict.cause, verdict.nextStep].filter(Boolean).join(' ')

    return (
        <Tooltip title={tooltip}>
            <span
                className={`flex items-start gap-1 text-xs min-w-0 ${
                    verdict.isMismatch ? 'text-warning' : 'text-success'
                }`}
                data-attr="experiment-exposure-split-verdict"
            >
                <Icon className="text-sm shrink-0 mt-px" />
                <span>{verdict.label}</span>
            </span>
        </Tooltip>
    )
}

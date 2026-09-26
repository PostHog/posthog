import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { ExposureSplitVerdict } from './exposureSplitVerdict'

interface ExposureSplitNoticeProps {
    verdict: ExposureSplitVerdict
    pValue: number
    onEditExposureCriteria: () => void
}

/**
 * The chi-squared verdict in full, for the expanded exposures panel. A mismatch names the
 * likeliest cause and the next step, following MultiVariantBiasWarning.
 */
export function ExposureSplitNotice({
    verdict,
    pValue,
    onEditExposureCriteria,
}: ExposureSplitNoticeProps): JSX.Element {
    if (!verdict.isMismatch) {
        return (
            <div className="flex items-center gap-1 text-xs mt-2 flex-wrap">
                <span className="flex items-center gap-1 text-success">
                    <IconCheckCircle className="text-sm" />
                    <span>{verdict.headline}</span>
                </span>
                <span className="text-muted">{verdict.cause}</span>
                <span className="text-muted">(p = {pValue.toFixed(3)})</span>
            </div>
        )
    }

    return (
        <LemonBanner type="warning" className="mt-2">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-0">
                    <div className="font-semibold">
                        {verdict.headline} <span className="font-normal">(p = {pValue.toExponential(2)})</span>
                    </div>
                    {verdict.cause && <p className="m-0 mt-1">{verdict.cause}</p>}
                    {verdict.nextStep && <p className="m-0 mt-1">{verdict.nextStep}</p>}
                    <p className="m-0 mt-1">
                        <Link to="https://posthog.com/docs/experiments/exposures" target="_blank">
                            More on how exposures are counted
                        </Link>
                    </p>
                </div>
                {verdict.suggestsExposureCriteriaFix && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        className="flex-shrink-0"
                        data-attr="experiment-exposure-split-edit-criteria"
                        onClick={onEditExposureCriteria}
                    >
                        Edit exposure criteria
                    </LemonButton>
                )}
            </div>
        </LemonBanner>
    )
}

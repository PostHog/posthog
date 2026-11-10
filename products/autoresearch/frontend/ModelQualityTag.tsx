import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { MODEL_QUALITY_THRESHOLDS, ModelQuality, ModelQualityVerdict } from './modelQuality'

const VERDICT_TAG_TYPE: Record<ModelQualityVerdict, LemonTagType> = {
    Strong: 'success',
    Fair: 'warning',
    Weak: 'danger',
}

function formatAuc(auc: number | null | undefined): string {
    return auc == null ? 'not measured' : auc.toFixed(3)
}

export function ModelQualityTag({
    quality,
    holdoutAuc,
    realizedAuc,
}: {
    quality: ModelQuality
    holdoutAuc: number | null | undefined
    realizedAuc: number | null | undefined
}): JSX.Element {
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <div>
                        {quality.basis === 'confirmed'
                            ? `Realized AUC ${quality.auc.toFixed(3)}, measured on real outcomes of past predictions.`
                            : `Holdout AUC ${quality.auc.toFixed(3)}, measured on test data only. Real outcomes are not checked yet.`}
                    </div>
                    <div>
                        AUC shows how well the model ranks people who do the target above people who don't. 0.5 is
                        random and 1.0 is perfect.
                    </div>
                    <div>
                        Strong is {MODEL_QUALITY_THRESHOLDS.strong.toFixed(2)} or more, Fair is{' '}
                        {MODEL_QUALITY_THRESHOLDS.fair.toFixed(2)} to {MODEL_QUALITY_THRESHOLDS.strong.toFixed(2)}, and
                        Weak is below {MODEL_QUALITY_THRESHOLDS.fair.toFixed(2)}.
                    </div>
                    <div className="text-xs">
                        Holdout AUC: {formatAuc(holdoutAuc)}. Realized AUC: {formatAuc(realizedAuc)}.
                    </div>
                </div>
            }
        >
            <LemonTag type={VERDICT_TAG_TYPE[quality.verdict]}>{quality.verdict}</LemonTag>
        </Tooltip>
    )
}

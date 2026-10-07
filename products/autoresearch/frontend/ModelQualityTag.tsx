import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { MODEL_QUALITY_LABEL, ModelQualityLevel, liftSentence, modelQuality } from './modelQuality'

const QUALITY_TAG_TYPE: Record<ModelQualityLevel, LemonTagType> = {
    strong: 'success',
    fair: 'warning',
    weak: 'danger',
}

function formatAuc(auc: number | null | undefined): string {
    return auc == null ? 'not measured yet' : auc.toFixed(3)
}

export function ModelQualityTag({
    holdoutAuc,
    realizedAuc,
    liftAt10,
    isPreliminary,
}: {
    holdoutAuc: number | null | undefined
    realizedAuc: number | null | undefined
    liftAt10?: number | null
    isPreliminary?: boolean | null
}): JSX.Element {
    const quality = modelQuality(holdoutAuc, realizedAuc)
    if (!quality) {
        return <span className="text-secondary">—</span>
    }
    const lift = liftSentence(liftAt10)
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <div>
                        {quality.source === 'realized'
                            ? 'Based on real outcomes of past predictions.'
                            : 'Based on held-out training data. Real outcomes are not measured yet.'}
                    </div>
                    {lift && <div>{lift}</div>}
                    <div>Realized AUC: {formatAuc(realizedAuc)}</div>
                    <div>Holdout AUC: {formatAuc(holdoutAuc)}</div>
                </div>
            }
        >
            <LemonTag type={QUALITY_TAG_TYPE[quality.level]}>
                {MODEL_QUALITY_LABEL[quality.level]}
                {isPreliminary ? ' (preliminary)' : ''}
            </LemonTag>
        </Tooltip>
    )
}

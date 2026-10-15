import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { OfflineResultCellApi, OfflineResultReadApi, OfflineScorerVersionReadApi } from '../generated/api.schemas'
import { offlineResultLabel } from './offlineResultPresentation'
import { offlineScorePasses } from './offlineScoreInterpretation'

export function OfflineResultTag({
    result,
    scorer,
}: {
    result: OfflineResultCellApi | OfflineResultReadApi
    scorer: OfflineScorerVersionReadApi
}): JSX.Element {
    const passed = result.status === 'ok' ? offlineScorePasses(result.value, scorer) : null
    const error = result.status === 'error'
    const label = offlineResultLabel(result, scorer)
    const fullLabel = result.status === 'ok' && typeof result.value === 'number' ? String(result.value) : label
    return (
        <LemonTag
            type={error || passed === false ? 'danger' : passed === true ? 'success' : 'muted'}
            icon={
                error ? <IconWarning /> : passed === true ? <IconCheck /> : passed === false ? <IconX /> : <IconMinus />
            }
            title={passed === null ? fullLabel : `${passed ? 'Pass' : 'Fail'}: ${fullLabel}`}
            className="max-w-full"
        >
            <span className="truncate" translate="no">
                {label}
            </span>
        </LemonTag>
    )
}

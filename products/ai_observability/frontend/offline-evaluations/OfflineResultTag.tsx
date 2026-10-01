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
    return (
        <LemonTag
            type={error || passed === false ? 'danger' : passed === true ? 'success' : 'muted'}
            icon={
                error ? <IconWarning /> : passed === true ? <IconCheck /> : passed === false ? <IconX /> : <IconMinus />
            }
            title={passed === null ? label : `${passed ? 'Pass' : 'Fail'}: ${label}`}
            className="max-w-full"
        >
            <span className="truncate" translate="no">
                {label}
            </span>
        </LemonTag>
    )
}

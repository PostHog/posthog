import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TraceMetricChangeToneApi } from '../../../generated/api.schemas'

const TONE_TAG: Record<TraceMetricChangeToneApi, LemonTagType> = {
    [TraceMetricChangeToneApi.Good]: 'success',
    [TraceMetricChangeToneApi.Bad]: 'danger',
    [TraceMetricChangeToneApi.Neutral]: 'muted',
}

export interface ChangeTagProps {
    label: string
    tone: TraceMetricChangeToneApi
}

export function ChangeTag({ label, tone }: ChangeTagProps): JSX.Element {
    return (
        <LemonTag type={TONE_TAG[tone]} size="small" className="whitespace-nowrap tabular-nums" translate="no">
            {label}
        </LemonTag>
    )
}

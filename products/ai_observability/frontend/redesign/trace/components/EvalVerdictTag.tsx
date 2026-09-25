import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { EvalVerdict } from '../types'

const VERDICTS: Record<EvalVerdict, { label: string; type: LemonTagType }> = {
    pass: { label: 'Pass', type: 'success' },
    fail: { label: 'Fail', type: 'danger' },
    na: { label: 'N/A', type: 'muted' },
}

export interface EvalVerdictTagProps {
    verdict: EvalVerdict
}

export function EvalVerdictTag({ verdict }: EvalVerdictTagProps): JSX.Element {
    return (
        <LemonTag type={VERDICTS[verdict].type} size="small">
            {VERDICTS[verdict].label}
        </LemonTag>
    )
}

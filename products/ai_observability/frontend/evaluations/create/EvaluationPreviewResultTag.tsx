import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import type { LemonTagProps } from '@posthog/lemon-ui'

import type { PreviewOutcomeEnumApi } from '../../generated/api.schemas'
import type { PreviewRunResult } from './previewRuns'

const OUTCOME_TAGS: Record<PreviewOutcomeEnumApi, { type: LemonTagProps['type']; label: string }> = {
    pass: { type: 'success', label: 'Pass' },
    fail: { type: 'danger', label: 'Fail' },
    na: { type: 'muted', label: 'N/A' },
    error: { type: 'danger', label: 'Error' },
}

export function EvaluationPreviewResultTag({ result }: { result: PreviewRunResult }): JSX.Element {
    const tag = result.outcome ? OUTCOME_TAGS[result.outcome] : { type: 'muted' as const, label: result.value }
    return (
        // The tooltip renders in a portal outside the preview, so it needs its own capture opt-out.
        <Tooltip title={result.detail ? <span className="ph-no-capture">{result.detail}</span> : undefined}>
            <LemonTag
                size="small"
                type={tag.type}
                className="shrink-0 animate-fade-in motion-reduce:animate-none"
                data-attr="llma-evaluation-create-preview-result"
            >
                {tag.label}
            </LemonTag>
        </Tooltip>
    )
}

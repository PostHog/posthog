import { LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export interface TraceIdChipProps {
    traceId: string
}

export function TraceIdChip({ traceId }: TraceIdChipProps): JSX.Element {
    return (
        <LemonTag weight="normal">
            <CopyToClipboardInline
                explicitValue={traceId}
                description="trace ID"
                className="font-mono"
                iconSize="xsmall"
            >
                {traceId.slice(0, 8)}
            </CopyToClipboardInline>
        </LemonTag>
    )
}

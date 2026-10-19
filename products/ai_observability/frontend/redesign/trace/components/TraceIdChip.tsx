import { LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

const HEX_ID_PATTERN = /^[0-9a-f-]{16,}$/i

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
                {HEX_ID_PATTERN.test(traceId) ? (
                    <span>{traceId.slice(0, 8)}</span>
                ) : (
                    <span className="block max-w-48 truncate">{traceId}</span>
                )}
            </CopyToClipboardInline>
        </LemonTag>
    )
}

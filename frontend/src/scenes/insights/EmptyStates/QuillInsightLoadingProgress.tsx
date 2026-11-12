import { Text } from '@posthog/quill'

import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

export function QuillInsightLoadingProgress({
    rowsRead,
    estimatedRows,
    bytesRead,
    bytesPerSecond,
    cpuUtilization,
}: {
    rowsRead: number
    estimatedRows?: number | null
    bytesRead: number
    bytesPerSecond: number
    cpuUtilization: number
}): JSX.Element {
    const total = estimatedRows && estimatedRows >= rowsRead ? ` / ${humanFriendlyNumber(estimatedRows)}` : ''
    return (
        <div translate="no" className="flex flex-wrap justify-center gap-x-3">
            <Text size="xs" variant="muted" render={<span />}>
                {`${humanFriendlyNumber(rowsRead, 0)}${total} rows`}
            </Text>
            <Text size="xs" variant="muted" render={<span />}>
                {`${humanizeBytes(bytesRead)} (${humanizeBytes(bytesPerSecond)}/s)`}
            </Text>
            <Text size="xs" variant="muted" render={<span />}>
                {`CPU ${humanFriendlyNumber(cpuUtilization, 0)}%`}
            </Text>
        </div>
    )
}

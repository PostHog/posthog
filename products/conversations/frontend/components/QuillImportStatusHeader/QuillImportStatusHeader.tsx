import { Badge, Text } from '@posthog/quill'

import { ImportStatus } from '../ImportStatusHeader/ImportStatusHeader'

function QuillImportStatusBadge({ status }: { status: ImportStatus }): JSX.Element {
    if (status === 'running' || status === 'pending') {
        return <Badge variant="warning">Syncing</Badge>
    }

    if (status === 'completed') {
        return <Badge variant="success">Done</Badge>
    }

    return <Badge variant="destructive">Failed</Badge>
}

export function QuillImportStatusHeader({
    status,
    progressLabel,
    latestError,
}: {
    status: ImportStatus | undefined
    progressLabel: string | null
    latestError: string | null | undefined
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" weight="medium" render={<span />}>
                    Import status
                </Text>
                {status ? <QuillImportStatusBadge status={status} /> : null}
                {progressLabel ? (
                    <Text size="xs" variant="muted" render={<span translate="no" />}>
                        {progressLabel}
                    </Text>
                ) : null}
            </div>
            {status === 'failed' && latestError ? (
                <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                    {latestError}
                </Text>
            ) : null}
        </div>
    )
}

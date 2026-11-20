import { LemonTag } from '@posthog/lemon-ui'

export type ImportStatus = 'pending' | 'running' | 'completed' | 'failed'

function ImportStatusTag({ status }: { status: ImportStatus }): JSX.Element {
    if (status === 'running' || status === 'pending') {
        return (
            <LemonTag type="warning" size="small">
                Syncing
            </LemonTag>
        )
    }
    if (status === 'completed') {
        return (
            <LemonTag type="success" size="small">
                Done
            </LemonTag>
        )
    }
    return (
        <LemonTag type="danger" size="small">
            Failed
        </LemonTag>
    )
}

export function ImportStatusHeader({
    status,
    progressLabel,
    latestError,
}: {
    status: ImportStatus | undefined
    progressLabel: string | null
    latestError: string | null | undefined
}): JSX.Element {
    return (
        <>
            <div className="flex items-center gap-2">
                <span className="font-medium">Import status</span>
                {status ? <ImportStatusTag status={status} /> : null}
                {progressLabel ? <span className="text-xs text-muted-alt">{progressLabel}</span> : null}
            </div>
            {status === 'failed' && latestError ? <p className="text-xs text-danger m-0">{latestError}</p> : null}
        </>
    )
}

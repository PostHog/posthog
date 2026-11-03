import { JSONViewer } from 'lib/components/JSONViewer'

export interface NodeRawTabProps {
    raw: Record<string, unknown> | null
}

export function NodeRawTab({ raw }: NodeRawTabProps): JSX.Element {
    if (!raw) {
        return (
            <p className="m-0 text-secondary">
                This trace has no event of its own, so there is no raw event to show. Select a step to see its raw
                event.
            </p>
        )
    }
    return (
        <div className="overflow-auto rounded border border-primary bg-surface-primary p-2">
            <JSONViewer src={raw} name={null} collapsed={2} sortKeys />
        </div>
    )
}

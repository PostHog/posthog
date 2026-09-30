import { JSONViewer } from 'lib/components/JSONViewer'

export interface NodeRawTabProps {
    raw: Record<string, unknown>
}

export function NodeRawTab({ raw }: NodeRawTabProps): JSX.Element {
    return (
        <div className="overflow-auto rounded border border-primary bg-surface-primary p-2">
            <JSONViewer src={raw} name={null} collapsed={2} sortKeys />
        </div>
    )
}

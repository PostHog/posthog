import { PropertiesTable } from 'products/error_tracking/frontend/components/PropertiesTable'

export function FrameVariables({ variables }: { variables: Record<string, unknown> }): JSX.Element {
    const entries = Object.entries(variables) as [string, unknown][]

    return (
        <div className="border-t border-border">
            <PropertiesTable entries={entries} alternatingColors={false} />
        </div>
    )
}

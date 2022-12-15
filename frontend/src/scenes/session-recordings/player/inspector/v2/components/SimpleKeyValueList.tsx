// A React component that renders a list of key-value pairs in a simple way.

export interface SimpleKeyValueListProps {
    item: Record<string, any>
}

export function SimpleKeyValueList({ item }: SimpleKeyValueListProps): JSX.Element {
    return (
        <div className="text-xs space-y-1 max-w-full">
            {Object.entries(item).map(([key, value]) => (
                <div key={key} className="flex gap-4 items-start justify-between overflow-hidden">
                    <span className="font-semibold">{key}</span>
                    <span className="text-primary-alt break-all">{JSON.stringify(value, null, 2)}</span>
                </div>
            ))}
        </div>
    )
}

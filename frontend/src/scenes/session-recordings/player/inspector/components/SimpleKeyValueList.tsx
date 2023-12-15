// A React component that renders a list of key-value pairs in a simple way.

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export interface SimpleKeyValueListProps {
    item: Record<string, any>
    emptyMessage?: string | JSX.Element | null
}

export function SimpleKeyValueList({ item, emptyMessage }: SimpleKeyValueListProps): JSX.Element {
    return (
        <div className="text-xs space-y-1 max-w-full">
            {Object.entries(item).map(([key, value]) => (
                <div key={key} className="flex gap-4 items-start justify-between overflow-hidden">
                    <span className="font-semibold">
                        <PropertyKeyInfo value={key} />
                    </span>
                    <pre className="text-primary-alt break-all mb-0">{JSON.stringify(value, null, 2)}</pre>
                </div>
            ))}
            {Object.keys(item).length === 0 && emptyMessage}
        </div>
    )
}

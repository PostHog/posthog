import { ReactNode } from 'react'

import { Button, Text } from '@posthog/quill'

interface CatalogBulkBarProps {
    selectedLabel: string
    onClear: () => void
    children: ReactNode
    dataAttr: string
}

export function CatalogBulkBar({ selectedLabel, onClear, children, dataAttr }: CatalogBulkBarProps): JSX.Element {
    return (
        <div
            className="sticky bottom-4 z-10 flex flex-wrap items-center gap-2 self-center rounded-md border border-border bg-surface-tertiary px-2 py-1 shadow-lg"
            data-attr={dataAttr}
        >
            <Text size="xs" className="tabular-nums">
                {selectedLabel}
            </Text>
            {children}
            <Button size="sm" onClick={onClear} data-attr={`${dataAttr}-clear`}>
                Clear selection
            </Button>
        </div>
    )
}

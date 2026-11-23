import { useState } from 'react'

export interface ExpandedRowIds {
    isExpanded: (rowId: string) => boolean
    toggle: (rowId: string) => void
}

export function useExpandedRowIds(onExpand: (rowId: string) => void): ExpandedRowIds {
    const [expandedIds, setExpandedIds] = useState<string[]>([])

    return {
        isExpanded: (rowId) => expandedIds.includes(rowId),
        toggle: (rowId) => {
            if (expandedIds.includes(rowId)) {
                setExpandedIds(expandedIds.filter((id) => id !== rowId))
                return
            }
            setExpandedIds([...expandedIds, rowId])
            onExpand(rowId)
        },
    }
}

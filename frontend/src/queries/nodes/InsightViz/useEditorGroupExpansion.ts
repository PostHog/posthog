import { useState } from 'react'

export function useEditorGroupExpansion(
    defaultExpanded: boolean | undefined,
    hasContent: boolean
): [boolean, (v: boolean) => void, boolean] {
    const [isRowExpanded, setIsRowExpanded] = useState(() => {
        // Auto-expand when there's configured content, otherwise use the default
        return hasContent || (defaultExpanded ?? true)
    })

    const isExpandable = defaultExpanded != undefined

    return [isRowExpanded, setIsRowExpanded, isExpandable]
}

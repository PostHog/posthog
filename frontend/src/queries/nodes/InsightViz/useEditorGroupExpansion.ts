import { useState } from 'react'

import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

export function isEditorGroupExpandedByDefault(defaultExpanded: boolean | undefined, hasContent: boolean): boolean {
    // Snapshots should display all editor filter groups expanded by default
    if (inStorybook() || inStorybookTestRunner()) {
        return true
    }
    // Auto-expand when there's configured content, otherwise use the default
    return hasContent || (defaultExpanded ?? true)
}

export function useEditorGroupExpansion(
    defaultExpanded: boolean | undefined,
    hasContent: boolean
): [boolean, (v: boolean) => void, boolean] {
    const [isRowExpanded, setIsRowExpanded] = useState(() =>
        isEditorGroupExpandedByDefault(defaultExpanded, hasContent)
    )

    const isExpandable = defaultExpanded != undefined

    return [isRowExpanded, setIsRowExpanded, isExpandable]
}

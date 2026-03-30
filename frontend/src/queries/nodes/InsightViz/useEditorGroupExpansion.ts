import { useState } from 'react'

import { inStorybook, inStorybookTestRunner } from 'lib/utils'

/**
 * Shared expansion state for editor filter groups.
 * Returns [isExpanded, setIsExpanded, isExpandable].
 */
export function useEditorGroupExpansion(
    defaultExpanded: boolean | undefined,
    hasContent: boolean
): [boolean, (v: boolean) => void, boolean] {
    const [isRowExpanded, setIsRowExpanded] = useState(() => {
        // Snapshots will display all editor filter groups by default
        if (inStorybook() || inStorybookTestRunner()) {
            return true
        }

        // Auto-expand when there's configured content, otherwise use the default
        return hasContent || (defaultExpanded ?? true)
    })

    // If defaultExpanded is not set, the group is not expandable
    const isExpandable = defaultExpanded != undefined

    return [isRowExpanded, setIsRowExpanded, isExpandable]
}

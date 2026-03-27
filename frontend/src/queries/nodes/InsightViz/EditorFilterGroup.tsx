import clsx from 'clsx'
import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { inStorybook, inStorybookTestRunner, slugify } from 'lib/utils'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

import { EditorFilterItems } from './EditorFilterItems'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insightProps: InsightLogicProps
    query: InsightQueryNode
}

export function EditorFilterGroup({ insightProps, editorFilterGroup }: EditorFilterGroupProps): JSX.Element {
    const { title, defaultExpanded, editorFilters } = editorFilterGroup
    const [isRowExpanded, setIsRowExpanded] = useState(() => {
        // Snapshots will display all editor filter groups by default
        if (inStorybook() || inStorybookTestRunner()) {
            return true
        }

        // If not specified, the group is expanded
        return defaultExpanded ?? true
    })

    // If defaultExpanded is not set, the group is not expandable
    const isExpandable = defaultExpanded != undefined

    return (
        <div>
            {isExpandable && (
                <LemonButton
                    fullWidth
                    onClick={() => setIsRowExpanded(!isRowExpanded)}
                    sideIcon={isRowExpanded ? <IconCollapse /> : <IconExpand />}
                    title={isRowExpanded ? 'Show less' : 'Show more'}
                    data-attr={'editor-filter-group-collapse-' + slugify(title)}
                >
                    <div className="flex items-center gap-2 font-semibold">
                        <span>{title}</span>
                    </div>
                </LemonButton>
            )}

            {isRowExpanded && (
                <div
                    className={clsx('flex flex-col gap-2', {
                        'border rounded p-2 mt-1': isExpandable && isRowExpanded,
                    })}
                >
                    <EditorFilterItems editorFilters={editorFilters} insightProps={insightProps} />
                </div>
            )}
        </div>
    )
}

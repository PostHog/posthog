import clsx from 'clsx'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { slugify } from 'lib/utils'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

import { EditorFilterGroupTile } from './EditorFilterGroupTile'
import { EditorFilterItems } from './EditorFilterItems'
import { useEditorGroupExpansion } from './useEditorGroupExpansion'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insightProps: InsightLogicProps
    query: InsightQueryNode
    asTile?: boolean
    queryKind?: string
}

export function EditorFilterGroup({
    insightProps,
    editorFilterGroup,
    asTile,
    queryKind,
}: EditorFilterGroupProps): JSX.Element {
    const { title, defaultExpanded, editorFilters, collapsedSummary } = editorFilterGroup
    const hasContent = !!collapsedSummary
    const [isRowExpanded, setIsRowExpanded, isExpandable] = useEditorGroupExpansion(defaultExpanded, hasContent)

    if (asTile) {
        return (
            <EditorFilterGroupTile
                insightProps={insightProps}
                editorFilterGroup={editorFilterGroup}
                queryKind={queryKind}
            />
        )
    }

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
                        {!isRowExpanded && collapsedSummary && (
                            <span className="text-xs font-normal text-secondary">{collapsedSummary}</span>
                        )}
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

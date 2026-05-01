import clsx from 'clsx'
import posthog from 'posthog-js'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { slugify } from 'lib/utils'

import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

import { EditorFilterItems } from './EditorFilterItems'
import { useEditorGroupExpansion } from './useEditorGroupExpansion'

export interface EditorFilterGroupTileProps {
    editorFilterGroup: InsightEditorFilterGroup
    insightProps: InsightLogicProps
    queryKind?: string
}

export function EditorFilterGroupTile({
    insightProps,
    editorFilterGroup,
    queryKind,
}: EditorFilterGroupTileProps): JSX.Element {
    const { title, defaultExpanded, editorFilters, collapsedSummary, headerExtra } = editorFilterGroup
    const hasContent = !!collapsedSummary
    const [isRowExpanded, setIsRowExpanded, isExpandable] = useEditorGroupExpansion(defaultExpanded, hasContent)

    return (
        <div className="border rounded bg-surface-primary min-w-0">
            {isExpandable ? (
                <LemonButton
                    fullWidth
                    onClick={() => {
                        const newState = !isRowExpanded
                        setIsRowExpanded(newState)
                        posthog.capture('editor panel section toggled', {
                            section: title,
                            action: newState ? 'opened' : 'closed',
                            query_kind: queryKind,
                        })
                    }}
                    sideIcon={isRowExpanded ? <IconCollapse /> : <IconExpand />}
                    title={isRowExpanded ? 'Show less' : 'Show more'}
                    data-attr={'editor-filter-group-collapse-' + slugify(title)}
                    className={clsx('rounded-b-none px-1 py-1', isRowExpanded && 'border-b')}
                >
                    <div className={clsx('flex items-center gap-2 font-semibold min-w-0', headerExtra && 'flex-1')}>
                        <span className="shrink-0">{title}</span>
                        {!isRowExpanded && collapsedSummary && (
                            <span className="text-xs font-normal text-secondary truncate">{collapsedSummary}</span>
                        )}
                        {headerExtra && (
                            <div className="ml-auto shrink-0" onClick={(e) => e.stopPropagation()}>
                                {headerExtra}
                            </div>
                        )}
                    </div>
                </LemonButton>
            ) : (
                <div className="px-3 py-2 flex items-center justify-between">
                    <span className="font-semibold text-secondary">{title}</span>
                    {headerExtra}
                </div>
            )}
            <div
                className="grid transition-all duration-200 ease-in-out min-w-0"
                style={{ gridTemplateRows: isRowExpanded ? '1fr' : '0fr' }}
            >
                <div className="overflow-hidden min-w-0">
                    <div className="px-3 pb-3 pt-2 flex flex-col gap-2 min-w-0">
                        <EditorFilterItems editorFilters={editorFilters} insightProps={insightProps} />
                    </div>
                </div>
            </div>
        </div>
    )
}

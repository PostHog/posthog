import { useState } from 'react'
import type { InsightLogicProps, InsightModel, QueryInsightEditorFilterGroup } from '~/types'
import '../../../scenes/insights/EditorFilters/EditorFilterGroup.scss'
import { LemonButton } from 'lib/components/LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { slugify } from 'lib/utils'
import { LemonBadge } from 'lib/components/LemonBadge/LemonBadge'
import { PureField } from 'lib/forms/Field'
import { InsightQueryNode } from '~/queries/schema'

export interface EditorFilterGroupProps {
    editorFilterGroup: QueryInsightEditorFilterGroup
    insight: Partial<InsightModel>
    insightProps: InsightLogicProps
    query: InsightQueryNode
    setQuery: (node: InsightQueryNode) => void
}

export function EditorFilterGroup({
    query,
    setQuery,
    insightProps,
    editorFilterGroup,
}: EditorFilterGroupProps): JSX.Element {
    const { title, count, defaultExpanded = true, editorFilters } = editorFilterGroup
    const [isRowExpanded, setIsRowExpanded] = useState(defaultExpanded)

    return (
        <div key={title} className="EditorFilterGroup">
            {title && (
                <div className="EditorFilterGroup__title">
                    <LemonButton
                        status="stealth"
                        fullWidth
                        onClick={() => setIsRowExpanded(!isRowExpanded)}
                        sideIcon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                        title={isRowExpanded ? 'Show less' : 'Show more'}
                        data-attr={'editor-filter-group-collapse-' + slugify(title)}
                    >
                        <div className="flex items-center space-x-2 font-semibold">
                            <span>{title}</span>
                            <LemonBadge.Number count={count || 0} />
                        </div>
                    </LemonButton>
                </div>
            )}
            {isRowExpanded ? (
                <div className="EditorFilterGroup__content">
                    {editorFilters.map(({ label: Label, tooltip, showOptional, key, component: Component }) => {
                        return (
                            <div key={key}>
                                <PureField
                                    label={
                                        typeof Label === 'function' ? (
                                            <Label query={query} setQuery={setQuery} insightProps={insightProps} />
                                        ) : (
                                            Label
                                        )
                                    }
                                    info={tooltip}
                                    showOptional={showOptional}
                                >
                                    {Component ? (
                                        <Component query={query} setQuery={setQuery} insightProps={insightProps} />
                                    ) : null}
                                </PureField>
                            </div>
                        )
                    })}
                </div>
            ) : null}
        </div>
    )
}

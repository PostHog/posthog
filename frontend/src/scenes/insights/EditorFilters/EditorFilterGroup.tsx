import React, { useState } from 'react'
import { InsightEditorFilterGroup, InsightLogicProps, InsightModel } from '~/types'
import { cleanFilters } from '../utils/cleanFilters'
import { EditorFilterItemTitle } from './EditorFilterItemTitle'
import './EditorFilterGroup.scss'
import { LemonButton } from 'lib/components/LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { slugify } from 'lib/utils'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insight: Partial<InsightModel>
    insightProps: InsightLogicProps
}

export function EditorFilterGroup({ editorFilterGroup, insight, insightProps }: EditorFilterGroupProps): JSX.Element {
    const { title, editorFilters, count, defaultExpanded = true } = editorFilterGroup
    const [isRowExpanded, setIsRowExpanded] = useState(defaultExpanded)
    return (
        <div key={title} className="insights-filter-group">
            <div className="insights-filter-group-title">
                <LemonButton
                    type={'stealth'}
                    fullWidth
                    onClick={() => setIsRowExpanded(!isRowExpanded)}
                    sideIcon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                    title={isRowExpanded ? 'Show less' : 'Show more'}
                    style={{
                        fontWeight: 600,
                    }}
                    data-attr={'editor-filter-group-collapse-' + slugify(title)}
                >
                    {title}
                    {count ? <span className="insights-filter-group-count">{count}</span> : null}
                </LemonButton>
            </div>
            {isRowExpanded ? (
                <div className="insights-filter-group-content">
                    {editorFilters.map(({ label, tooltip, key, valueSelector, component: Component }) => (
                        <div key={key}>
                            {label ? <EditorFilterItemTitle label={label} tooltip={tooltip} /> : null}
                            {Component ? (
                                <Component
                                    insight={insight}
                                    insightProps={insightProps}
                                    filters={insight.filters ?? cleanFilters({})}
                                    value={(valueSelector ? valueSelector(insight) : insight?.filters?.[key]) ?? null}
                                />
                            ) : null}
                        </div>
                    ))}
                </div>
            ) : null}
        </div>
    )
}

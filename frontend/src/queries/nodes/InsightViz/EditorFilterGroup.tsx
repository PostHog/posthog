import { useState } from 'react'
import type { InsightLogicProps, InsightModel, InsightEditorFilterGroup } from '~/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { slugify } from 'lib/utils'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge/LemonBadge'
import { PureField } from 'lib/forms/Field'
import { InsightQueryNode } from '~/queries/schema'

import './EditorFilterGroup.scss'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insight: Partial<InsightModel>
    insightProps: InsightLogicProps
    query: InsightQueryNode
}

export function EditorFilterGroup({ insightProps, editorFilterGroup }: EditorFilterGroupProps): JSX.Element {
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
                        if (Component && Component.name === 'component') {
                            throw new Error(
                                `Component for filter ${key} is an anonymous function, which is not a valid React component! Use a named function instead.`
                            )
                        }
                        return (
                            <div key={key}>
                                <PureField
                                    label={typeof Label === 'function' ? <Label insightProps={insightProps} /> : Label}
                                    info={tooltip}
                                    showOptional={showOptional}
                                >
                                    {Component ? <Component insightProps={insightProps} /> : null}
                                </PureField>
                            </div>
                        )
                    })}
                </div>
            ) : null}
        </div>
    )
}

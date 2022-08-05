import React, { useState } from 'react'
import { InsightEditorFilterGroup, InsightLogicProps, InsightModel } from '~/types'
import { cleanFilters } from '../utils/cleanFilters'
import { EditorFilterItemTitle } from './EditorFilterItemTitle'
import './EditorFilterGroup.scss'
import { LemonButton } from 'lib/components/LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { slugify } from 'lib/utils'
import { LemonBubble } from 'lib/components/LemonBubble/LemonBubble'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import clsx from 'clsx'

export interface EditorFilterGroupProps {
    editorFilterGroup: InsightEditorFilterGroup
    insight: Partial<InsightModel>
    insightProps: InsightLogicProps
}

export function EditorFilterGroup({ editorFilterGroup, insight, insightProps }: EditorFilterGroupProps): JSX.Element {
    const { title, editorFilters, count, defaultExpanded = true } = editorFilterGroup
    const [isRowExpanded, setIsRowExpanded] = useState(defaultExpanded)

    const { featureFlags } = useValues(featureFlagLogic)
    const usingEditorPanels = featureFlags[FEATURE_FLAGS.INSIGHT_EDITOR_PANELS]

    return (
        <div
            key={title}
            className={clsx('EditorFilterGroup', {
                'EditorFilterGroup--editorpanels': usingEditorPanels,
            })}
        >
            {title && (
                <div className="EditorFilterGroup__title">
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
                        <div className="flex items-center space-x-2">
                            <span>{title}</span>
                            <LemonBubble count={count} />
                        </div>
                    </LemonButton>
                </div>
            )}
            {!usingEditorPanels || isRowExpanded ? (
                <div className="EditorFilterGroup__content">
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

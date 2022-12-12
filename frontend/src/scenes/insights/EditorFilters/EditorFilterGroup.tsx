import { useState } from 'react'
import { EditorFilterProps, InsightEditorFilterGroup, InsightLogicProps, InsightModel } from '~/types'
import { cleanFilters } from '../utils/cleanFilters'
import './EditorFilterGroup.scss'
import { LemonButton } from 'lib/components/LemonButton'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { slugify } from 'lib/utils'
import { LemonBadge } from 'lib/components/LemonBadge/LemonBadge'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import clsx from 'clsx'
import { PureField } from 'lib/forms/Field'

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
            {!usingEditorPanels || isRowExpanded ? (
                <div className="EditorFilterGroup__content">
                    {editorFilters.map(
                        ({ label: Label, tooltip, showOptional, key, valueSelector, component: Component }) => {
                            // Don't calculate editorFilterProps if not needed
                            const editorFilterProps: EditorFilterProps | null =
                                typeof Label === 'function' || Component
                                    ? {
                                          insight,
                                          insightProps,
                                          filters: insight.filters ?? cleanFilters({}),
                                          value:
                                              (valueSelector ? valueSelector(insight) : insight?.filters?.[key]) ??
                                              null,
                                      }
                                    : null
                            return (
                                <div key={key}>
                                    <PureField
                                        label={
                                            typeof Label === 'function' ? (
                                                <Label {...(editorFilterProps as EditorFilterProps)} />
                                            ) : (
                                                Label
                                            )
                                        }
                                        info={tooltip}
                                        showOptional={showOptional}
                                    >
                                        {Component ? <Component {...(editorFilterProps as EditorFilterProps)} /> : null}
                                    </PureField>
                                </div>
                            )
                        }
                    )}
                </div>
            ) : null}
        </div>
    )
}

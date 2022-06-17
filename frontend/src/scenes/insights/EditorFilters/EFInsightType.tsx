import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import React from 'react'
import { EditorFilterProps, InsightType } from '~/types'
import clsx from 'clsx'
import { CSSTransition } from 'react-transition-group'
import './EFInsightType.scss'
import { LemonButton, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

export function EFInsightTypeHorizontal(): JSX.Element {
    const { setActiveView } = useActions(insightLogic)
    const { insight } = useValues(insightLogic)

    return (
        <div className="EFInsightType">
            {Object.entries(INSIGHT_TYPES_METADATA).map(([key, meta]) => {
                const selected = insight.filters?.insight === key

                return (
                    <LemonButton
                        key={key}
                        type={selected ? 'highlighted' : 'stealth'}
                        onClick={() => setActiveView(key as InsightType)}
                        title={meta.name}
                    >
                        <span
                            className={clsx('EFInsightType-button-content', {
                                'EFInsightType-button-content--selected': selected,
                            })}
                        >
                            <meta.icon color="var(--primary-alt)" noBackground />
                            <CSSTransition
                                in={selected}
                                timeout={200}
                                classNames="EFInsightType-button-content-text-"
                                mountOnEnter
                                unmountOnExit
                            >
                                <span className="EFInsightType-button-content-text">{meta.name}</span>
                            </CSSTransition>
                        </span>
                    </LemonButton>
                )
            })}
        </div>
    )
}

const INSIGHT_TYPE_OPTIONS: LemonSelectOptions = Object.entries(INSIGHT_TYPES_METADATA).reduce((acc, [key, meta]) => {
    return {
        ...acc,
        [key]: {
            label: meta.name,
            icon: meta.icon ? <meta.icon color="#747EA2" noBackground /> : null,
        },
    }
}, {})

export function EFInsightType({ value }: EditorFilterProps): JSX.Element {
    const { setActiveView } = useActions(insightLogic)

    return (
        <LemonSelect
            options={INSIGHT_TYPE_OPTIONS}
            value={value}
            onChange={(v: any): void => {
                if (v) {
                    setActiveView(v)
                }
            }}
            type="stealth"
            outlined
            fullWidth
            data-attr="insight-type"
        />
    )
}

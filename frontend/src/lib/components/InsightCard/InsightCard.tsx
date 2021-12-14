import clsx from 'clsx'
import { capitalizeFirstLetter, dateFilterToText } from 'lib/utils'
import React from 'react'
import { Layout } from 'react-grid-layout'
import { UNNAMED_INSIGHT_NAME } from 'scenes/insights/EmptyStates'
import { urls } from 'scenes/urls'
import { InsightColor, InsightModel } from '~/types'
import { Splotch, SplotchColor } from '../icons/Splotch'
import { LemonButton, LemonButtonWithPopup } from '../LemonButton'
import { More } from '../LemonButton/More'
import { Link } from '../Link'
import { ObjectTags } from '../ObjectTags'
import './InsightCard.scss'

export interface InsightCardProps {
    /** Insight to display. */
    insight: InsightModel
    /** Card index, for data-attr instrumentation. */
    index: number
    /** Whether the insight is loading. */
    loading: boolean
    /** Whether loading the insight resulted in an error. */
    apiError: boolean
    /** Whether the card should be highlighted. */
    highlighted: boolean
    /** Layout of the card on a grid. */
    layout?: Layout
    /** Callback for updating insight color.  */
    updateColor: (newColor: InsightColor | null) => void
}

function InsightMeta({
    insight,
    updateColor,
}: Pick<InsightCardProps, 'insight' | 'index' | 'updateColor'>): JSX.Element {
    const { short_id, name, description, tags, color, filters } = insight

    return (
        <div className="InsightMeta">
            <div>
                {color &&
                    color !== InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('InsightMeta__ribbon', color)} />
                    )}
                <div className="InsightMeta__main">
                    <div className="InsightMeta__top">
                        <h5>
                            {filters.insight} • {dateFilterToText(filters.date_from, filters.date_to, '?')}
                        </h5>
                        <div className="InsightMeta__controls">
                            <More
                                overlay={
                                    <>
                                        <LemonButtonWithPopup
                                            type="stealth"
                                            popup={{
                                                overlay: Object.values(InsightColor).map((availableColor) => (
                                                    <LemonButton
                                                        key={availableColor}
                                                        type="stealth"
                                                        onClick={() => updateColor(availableColor)}
                                                        icon={
                                                            <Splotch color={availableColor as string as SplotchColor} />
                                                        }
                                                        fullWidth
                                                    >
                                                        {capitalizeFirstLetter(availableColor)}
                                                    </LemonButton>
                                                )),
                                                placement: 'right-start',
                                                fallbackPlacements: ['left-start'],
                                            }}
                                            fullWidth
                                        >
                                            Change color
                                        </LemonButtonWithPopup>
                                    </>
                                }
                            />
                        </div>
                    </div>
                    <Link to={urls.insightView(short_id)}>
                        <h4 title={name}>{name || <i>{UNNAMED_INSIGHT_NAME}</i>}</h4>
                    </Link>
                    <div className="InsightMeta__description">{description || <i>No description</i>}</div>
                    {tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
                </div>
            </div>
        </div>
    )
}

function InsightViz({}: Pick<InsightCardProps, 'insight' | 'index' | 'loading' | 'apiError'>): JSX.Element {
    return <div className="InsightViz">Imagine a graph here</div>
}

export function InsightCard({
    insight,
    index,
    loading,
    apiError,
    highlighted,
    updateColor,
}: InsightCardProps): JSX.Element {
    return (
        <div className={clsx('InsightCard', highlighted && 'InsightCard--highlighted')}>
            <InsightViz insight={insight} index={index} loading={loading} apiError={apiError} />
            <InsightMeta insight={insight} index={index} updateColor={updateColor} />
        </div>
    )
}

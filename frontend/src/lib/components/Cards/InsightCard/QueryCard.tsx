import clsx from 'clsx'
import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import React, { useState } from 'react'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { LemonMenuItemList } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { urls } from 'scenes/urls'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightSceneSource } from '~/types'

import { InsightCardProps } from './InsightCard'
import { InsightDetails } from './InsightDetails'
import { InsightMetaContent } from './InsightMeta'
import { TopHeading } from './TopHeading'

export interface QueryCardProps extends Pick<InsightCardProps, 'highlighted' | 'ribbonColor' | 'className' | 'style'> {
    query: Node
    title: string
    description?: string
    context?: QueryContext
    sceneSource?: InsightSceneSource
    /** Attach ourselves to another logic, such as the scene logic */
    attachTo?: BuiltLogic | LogicWrapper
}

/** This is like InsightCard, except for presentation of queries that aren't saved insights. */
export const QueryCard = React.forwardRef<HTMLDivElement, QueryCardProps>(function QueryCard(
    { query, title, description, context, highlighted, ribbonColor, className, sceneSource, attachTo, ...divProps },
    ref
): JSX.Element {
    const { theme } = useValues(themeLogic)

    const [areDetailsShown, setAreDetailsShown] = useState(false)

    return (
        <div
            className={clsx('InsightCard border', highlighted && 'InsightCard--highlighted', className)}
            data-attr="insight-card"
            {...divProps}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ ...divProps?.style, ...theme?.boxStyle }}
            ref={ref}
        >
            <ErrorBoundary exceptionProps={{ feature: 'insight' }}>
                <CardMeta
                    ribbonColor={ribbonColor}
                    setAreDetailsShown={setAreDetailsShown}
                    areDetailsShown={areDetailsShown}
                    topHeading={<TopHeading query={query} />}
                    content={<InsightMetaContent title={title} description={description} />}
                    metaDetails={<InsightDetails query={query} />}
                    samplingFactor={
                        'samplingFactor' in query && typeof query.samplingFactor === 'number'
                            ? query.samplingFactor
                            : undefined
                    }
                    moreButtons={
                        <LemonMenuItemList
                            items={[
                                {
                                    label: 'Open as new insight',
                                    to: urls.insightNew({ query, sceneSource }),
                                },
                            ]}
                        />
                    }
                    showEditingControls
                />
                <div className="InsightCard__viz">
                    <Query attachTo={attachTo} query={query} readOnly embedded context={context} />
                </div>
            </ErrorBoundary>
        </div>
    )
})

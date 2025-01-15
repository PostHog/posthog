import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { LemonMenuItemList } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import React, { useEffect, useState } from 'react'
import { Transition } from 'react-transition-group'
import { ENTERED, ENTERING } from 'react-transition-group/Transition'
import { maxLogic } from 'scenes/max/maxLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema'
import { SidePanelTab } from '~/types'

import { InsightCardProps } from './InsightCard'
import { InsightDetails } from './InsightDetails'
import { InsightMetaContent } from './InsightMeta'
import { TopHeading } from './TopHeading'

export interface QueryCardProps extends Pick<InsightCardProps, 'highlighted' | 'ribbonColor' | 'className' | 'style'> {
    query: Node
    title: string
    description?: string
}

export const MaxContext = React.createContext<((data: Record<string, string>) => void) | null>(null)

let uniqueNode = 0
function MaxContextWrapper({
    kind,
    title,
    content,
    children,
}: {
    kind: string
    title: string
    content: string | ((data: Record<string, string>) => string)
    children: React.ReactChild
}): JSX.Element {
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)
    const { user } = useValues(userLogic)
    const { registerSceneContext, deregisterSceneContext } = useActions(maxLogic)

    const [id] = useState(() => uniqueNode++)
    const [data, setData] = useState<Record<string, string>>({})

    useEffect(() => {
        const realContent = typeof content === 'function' ? content(data) : content
        registerSceneContext(id, kind, title, realContent)
        return () => deregisterSceneContext(id)
    }, [id, kind, title, content, JSON.stringify(data), registerSceneContext, deregisterSceneContext])

    return (
        <MaxContext.Provider value={setData}>
            <Transition in={sidePanelOpen && selectedTab === SidePanelTab.Max} timeout={100} mountOnEnter unmountOnExit>
                {(status) => (
                    <Tooltip title="Max is aware of this data" placement="left">
                        <ProfilePicture
                            user={{ hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }}
                            size="lg"
                            className={clsx(
                                'absolute -top-3 -right-3 z-10 mt-1 border bg-bg-light transition duration-100',
                                status === ENTERING || status === ENTERED
                                    ? 'scale-y-100 -scale-x-100 opacity-1'
                                    : 'scale-y-75 -scale-x-75 opacity-0'
                            )}
                        />
                    </Tooltip>
                )}
            </Transition>
            {children}
        </MaxContext.Provider>
    )
}

/** This is like InsightCard, except for presentation of queries that aren't saved insights. */
export const QueryCard = React.forwardRef<HTMLDivElement, QueryCardProps>(function QueryCard(
    { query, title, description, highlighted, ribbonColor, className, ...divProps },
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
            style={{ ...(divProps?.style ?? {}), ...(theme?.boxStyle ?? {}) }}
            ref={ref}
        >
            <MaxContextWrapper
                kind="query"
                title={title}
                content={(data) => `Query: ${JSON.stringify(query)}\nResults: ${data.resultsJson || 'no results yet'}`}
            >
                <ErrorBoundary tags={{ feature: 'insight' }}>
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
                                        to: urls.insightNew(undefined, undefined, query),
                                    },
                                ]}
                            />
                        }
                        showEditingControls
                    />
                    <div className="InsightCard__viz">
                        <Query query={query} readOnly embedded />
                    </div>
                </ErrorBoundary>
            </MaxContextWrapper>
        </div>
    )
})

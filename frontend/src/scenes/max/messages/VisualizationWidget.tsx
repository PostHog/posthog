import clsx from 'clsx'
import React, { useMemo, useState } from 'react'

import { IconCollapse, IconExpand, IconEye, IconHide, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import {
    ArtifactMessage,
    ArtifactSource,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isFunnelsQuery, isHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId } from '~/types'

import { MessageTemplate } from 'products/posthog_ai/frontend/api/primitives'

import { visualizationTypeToQuery } from '../utils'

const QUERY_CONTEXT_POSTHOG_AI: QueryContext = { limitContext: 'posthog_ai' } as const

export interface VisualizationWidgetProps {
    content: VisualizationArtifactContent
    /** Href for the "Open as insight" CTA; null/undefined hides the button. */
    openUrl?: string | null
    /** Tooltip for the CTA. */
    openTooltip?: string
    /** Controlled collapse state; omit for uncontrolled (starts expanded). */
    isCollapsed?: boolean
    onCollapsedChange?: (isCollapsed: boolean) => void
    /** Extra buttons rendered in the actions row before the CTA. */
    extraActions?: React.ReactNode
    /** Render only the widget body, for use inside an existing activity/message shell. */
    embedded?: boolean
}

/** Resolves the "Open as insight" CTA target for a visualization artifact. */
export function getArtifactOpenTarget(
    envelope: ArtifactMessage,
    content: VisualizationArtifactContent
): { url: string | null; tooltip: string } {
    if (envelope.source === ArtifactSource.Insight) {
        return { url: urls.insightView(envelope.artifact_id as InsightShortId), tooltip: 'Open insight' }
    }
    const query = visualizationTypeToQuery(content)
    return {
        url: query ? urls.insightNew({ query: query as InsightVizNode | DataVisualizationNode }) : null,
        tooltip: 'Open as new insight',
    }
}

/**
 * Atomic, runtime-agnostic visualization renderer. Runtime-specific behavior (scene coupling,
 * status gating, suggestion flows) belongs in the proxy renderers that compose this widget.
 */
export const VisualizationWidget = React.memo(function VisualizationWidget({
    content,
    openUrl,
    openTooltip = 'Open as new insight',
    isCollapsed: controlledCollapsed,
    onCollapsedChange,
    extraActions,
    embedded = false,
}: VisualizationWidgetProps): JSX.Element {
    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [internalCollapsed, setInternalCollapsed] = useState(false)
    const isCollapsed = controlledCollapsed ?? internalCollapsed
    const setCollapsed = (next: boolean): void => {
        setInternalCollapsed(next)
        onCollapsedChange?.(next)
    }

    // Build query from either artifact content or inline visualization message
    const query = useMemo(() => {
        return visualizationTypeToQuery(content)
    }, [content])

    // Get the raw query for height calculation
    const rawQuery = content.query

    const renderedContent = !query ? (
        <div className="flex items-center gap-1.5">
            <IconWarning className="text-xl text-danger" />
            <span>Failed to load visualization</span>
        </div>
    ) : (
        <div className="flex flex-col w-full">
            {!isCollapsed && (
                <div className={clsx('flex flex-col overflow-auto', isFunnelsQuery(rawQuery) ? 'h-[580px]' : 'h-96')}>
                    <Query query={query} readOnly embedded context={QUERY_CONTEXT_POSTHOG_AI} />
                </div>
            )}
            <div className={clsx('flex items-center justify-between', !isCollapsed && 'mt-2')}>
                {isInsightVizNode(query) ? (
                    <div className="flex items-center gap-1.5">
                        <LemonButton
                            sideIcon={isSummaryShown ? <IconCollapse /> : <IconExpand />}
                            onClick={() => setIsSummaryShown(!isSummaryShown)}
                            size="xsmall"
                            className="-m-1 shrink"
                            tooltip={isSummaryShown ? 'Hide definition' : 'Show definition'}
                        >
                            <h5 className="m-0 leading-none">
                                <TopHeading query={query} />
                            </h5>
                        </LemonButton>
                    </div>
                ) : (
                    <h5 className="m-0 leading-none">
                        <TopHeading query={query} />
                    </h5>
                )}
                <div className="flex items-center gap-1.5">
                    {extraActions}
                    {openUrl && (
                        <LemonButton
                            to={openUrl}
                            targetBlank
                            icon={<IconOpenInNew />}
                            size="xsmall"
                            tooltip={openTooltip}
                        />
                    )}
                    <LemonButton
                        icon={isCollapsed ? <IconEye /> : <IconHide />}
                        onClick={() => setCollapsed(!isCollapsed)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isCollapsed ? 'Show visualization' : 'Hide visualization'}
                    />
                </div>
            </div>
            {isInsightVizNode(query) && isSummaryShown && (
                <>
                    <SeriesSummary query={query.source} heading={null} />
                    {!isHogQLQuery(query.source) && (
                        <div className="flex flex-wrap gap-4 mt-1 *:grow">
                            <PropertiesSummary properties={query.source.properties} />
                            <InsightBreakdownSummary query={query.source} />
                        </div>
                    )}
                </>
            )}
        </div>
    )

    if (embedded) {
        return renderedContent
    }

    if (!query) {
        return (
            <MessageTemplate
                type="ai"
                className="w-full"
                wrapperClassName="w-full"
                boxClassName="flex flex-col w-full border-danger"
            >
                {renderedContent}
            </MessageTemplate>
        )
    }

    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            {renderedContent}
        </MessageTemplate>
    )
})

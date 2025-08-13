import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useMountedLogic, useValues } from 'kea'
import { AccessDenied } from 'lib/components/AccessDenied'
import { DebugCHQueries } from 'lib/components/CommandPalette/DebugCHQueries'
import { isEmptyObject, isObject } from 'lib/utils'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { ReloadInsight } from 'scenes/saved-insights/ReloadInsight'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ItemMode } from '~/types'

import { insightCommandLogic } from './insightCommandLogic'
import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'
import { InsightsNav } from './InsightNav/InsightsNav'
import { useAttachedLogic } from 'lib/logic/scene-plugin/useAttachedLogic'
import { useState } from 'react'
export interface InsightSceneProps {
    insightId: InsightShortId | 'new'
    tabId: string
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

let uniqueCount = 0
export function Insight({ insightId, attachTo }: InsightSceneProps): JSX.Element | null {
    // insightSceneLogic
    const { insightMode, insight, filtersOverride, variablesOverride, freshQuery } = useValues(insightSceneLogic)
    const [uniqueId] = useState(() => `${uniqueCount++}`)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || `new-${uniqueId}`,
        // don't use cached insight if we have filtersOverride
        cachedInsight:
            (isObject(filtersOverride) || isObject(variablesOverride)) && insight?.short_id === insightId
                ? insight
                : null,
        filtersOverride,
        variablesOverride,
    })
    const { insightProps, accessDeniedToInsight } = useValues(logic)

    // insightDataLogic
    const { query, showQueryEditor, showDebugPanel } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))

    useAttachedLogic(logic, attachTo)
    useAttachedLogic(insightDataLogic(insightProps), attachTo)

    const actuallyShowQueryEditor = insightMode === ItemMode.Edit && showQueryEditor

    const setQuery = (query: Node, isSourceUpdate?: boolean): void => {
        if (!isInsightVizNode(query) || isSourceUpdate) {
            setInsightQuery(query)
        }
    }

    if (accessDeniedToInsight) {
        return <AccessDenied object="insight" />
    }

    const dashboardOverridesExist =
        (isObject(filtersOverride) && !isEmptyObject(filtersOverride)) ||
        (isObject(variablesOverride) && !isEmptyObject(variablesOverride))
    const overrideType = isObject(filtersOverride) ? 'filters' : 'variables'

    if (!insight?.query) {
        return null
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className="Insight">
                <InsightPageHeader insightLogicProps={insightProps} />

                {dashboardOverridesExist && (
                    <LemonBanner type="warning" className="mb-4">
                        <div className="flex flex-row items-center justify-between gap-2">
                            <span>You are viewing this insight with {overrideType} from a dashboard</span>

                            <LemonButton type="secondary" to={urls.insightView(insightId as InsightShortId)}>
                                Discard dashboard {overrideType}
                            </LemonButton>
                        </div>
                    </LemonBanner>
                )}

                {insightMode === ItemMode.Edit && <InsightsNav />}

                {showDebugPanel && (
                    <div className="mb-4">
                        <DebugCHQueries insightId={insightProps.cachedInsight?.id} />
                    </div>
                )}

                {freshQuery ? <ReloadInsight /> : null}

                <Query
                    attachTo={attachTo}
                    query={isInsightVizNode(query) ? { ...query, full: true } : query}
                    setQuery={setQuery}
                    readOnly={insightMode !== ItemMode.Edit}
                    context={{
                        showOpenEditorButton: false,
                        showQueryEditor: actuallyShowQueryEditor,
                        showQueryHelp: insightMode === ItemMode.Edit && !containsHogQLQuery(query),
                        insightProps,
                        insightMode,
                    }}
                    filtersOverride={filtersOverride}
                    variablesOverride={variablesOverride}
                />
            </div>
        </BindLogic>
    )
}

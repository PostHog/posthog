import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import {
    JOURNEY_BUILDER_INSIGHT_PROPS,
    JOURNEY_NAME_INPUT_MAX_LENGTH,
    journeyBuilderLogic,
} from './journeyBuilderLogic'

const JOURNEY_BUILDER_CONTEXT: QueryContext<InsightVizNode> = {
    insightProps: JOURNEY_BUILDER_INSIGHT_PROPS as InsightLogicProps<InsightVizNode>,
}

export function JourneyBuilder(): JSX.Element {
    const { query, journeyName, isSaving } = useValues(journeyBuilderLogic)
    const { setQueryFromViz, setJourneyName, saveJourney, closeBuilder } = useActions(journeyBuilderLogic)
    const builderRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        builderRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, [])

    return (
        <div ref={builderRef} className="space-y-4">
            <LemonDivider />
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-lg m-0">Build journey</h3>
                    <LemonInput
                        value={journeyName}
                        onChange={setJourneyName}
                        placeholder="Journey name"
                        size="small"
                        className="w-64"
                        maxLength={JOURNEY_NAME_INPUT_MAX_LENGTH}
                    />
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" size="small" onClick={closeBuilder}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" size="small" loading={isSaving} onClick={() => saveJourney()}>
                        Save journey
                    </LemonButton>
                </div>
            </div>
            <InsightViz
                query={query}
                setQuery={(node) => setQueryFromViz(node as InsightVizNode<FunnelsQuery>)}
                editMode={true}
                uniqueKey="journey-builder"
                context={JOURNEY_BUILDER_CONTEXT}
            />
        </div>
    )
}

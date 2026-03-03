import { useActions, useValues } from 'kea'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { JOURNEY_BUILDER_INSIGHT_PROPS, journeyBuilderLogic } from './journeyBuilderLogic'

const JOURNEY_BUILDER_CONTEXT: QueryContext = {
    insightProps: JOURNEY_BUILDER_INSIGHT_PROPS,
}

export function JourneyBuilder(): JSX.Element {
    const { query, isSaving } = useValues(journeyBuilderLogic)
    const { setQuery, resetBuilder, closeBuilder } = useActions(journeyBuilderLogic)

    const handleCancel = (): void => {
        resetBuilder()
        closeBuilder()
    }

    return (
        <div className="space-y-4">
            <LemonDivider />
            <div className="flex items-center justify-between">
                <h3 className="font-semibold text-lg m-0">Build journey</h3>
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" size="small" onClick={handleCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={isSaving}
                        onClick={() => {
                            /* save modal — implemented in Step 10 */
                        }}
                    >
                        Save journey
                    </LemonButton>
                </div>
            </div>
            <InsightViz
                query={query}
                setQuery={(node) => setQuery(node as InsightVizNode<FunnelsQuery>)}
                editMode={true}
                uniqueKey="journey-builder"
                context={JOURNEY_BUILDER_CONTEXT}
            />
        </div>
    )
}

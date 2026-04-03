import { expectLogic } from 'kea-test-utils'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import { JOURNEY_BUILDER_INSIGHT_PROPS, journeyBuilderLogic } from './journeyBuilderLogic'

// Simulates the wiring that JourneyBuilder.tsx → InsightViz.tsx → insightVizDataLogic creates.
function mountFeedbackChain(
    builderLogic: ReturnType<typeof journeyBuilderLogic.build>,
    echoBackAction: 'setQuery' | 'setQueryFromViz'
): ReturnType<typeof insightVizDataLogic.build> {
    const vizProps: InsightLogicProps<InsightVizNode> = {
        ...JOURNEY_BUILDER_INSIGHT_PROPS,
        setQuery: (node: InsightVizNode) => {
            builderLogic.actions[echoBackAction](node as InsightVizNode<FunnelsQuery>)
        },
    } as InsightLogicProps<InsightVizNode>
    const dataLogic = insightDataLogic(JOURNEY_BUILDER_INSIGHT_PROPS)
    const vizLogic = insightVizDataLogic(vizProps as InsightLogicProps)
    dataLogic.mount()
    vizLogic.mount()
    return vizLogic
}

describe('journeyBuilderLogic', () => {
    let logic: ReturnType<typeof journeyBuilderLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = journeyBuilderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('setQuery feedback loop regression', () => {
        it('causes infinite recursion when insightVizDataLogic echoes back via setQuery (the old wiring)', () => {
            const vizLogic = mountFeedbackChain(logic, 'setQuery')

            expect(() => logic.actions.addStep(1)).toThrow(/Maximum call stack/)

            vizLogic.unmount()
        })

        it('does not loop when insightVizDataLogic echoes back via setQueryFromViz (the fix)', async () => {
            const vizLogic = mountFeedbackChain(logic, 'setQueryFromViz')

            expect(() => logic.actions.addStep(1)).not.toThrow()

            await expectLogic(logic).toMatchValues({
                stepCount: 2,
            })

            vizLogic.unmount()
        })
    })
})

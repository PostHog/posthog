import { expectLogic } from 'kea-test-utils'

import type { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelVizType } from '~/types'

import { customerJourneysLogic } from './customerJourneysLogic'

const timeToConvertQuery = {
    kind: 'InsightVizNode',
    source: {
        kind: 'FunnelsQuery',
        series: [],
        funnelsFilter: {
            funnelVizType: FunnelVizType.TimeToConvert,
        },
    },
} as InsightVizNode<FunnelsQuery>

describe('customerJourneysLogic', () => {
    let logic: ReturnType<typeof customerJourneysLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = customerJourneysLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('queryOverride', () => {
        it('can clear an overridden journey query', async () => {
            await expectLogic(logic, () => {
                logic.actions.setQueryOverride(timeToConvertQuery)
            }).toMatchValues({
                activeJourneyFullQuery: timeToConvertQuery,
                hasQueryOverride: true,
            })

            await expectLogic(logic, () => {
                logic.actions.clearQueryOverride()
            }).toMatchValues({
                activeJourneyFullQuery: null,
                hasQueryOverride: false,
            })
        })
    })
})

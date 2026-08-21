import {
    ConversionGoalFilter,
    MarketingAnalyticsRetentionQuery,
    MarketingAnalyticsRetentionReturningEvent,
    MarketingAnalyticsRetentionStartEvent,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import { marketingRetentionLogic } from './marketingRetentionLogic'

const GOAL_ID = 'goal-1'
const OTHER_GOAL_ID = 'goal-2'

const eventGoal = (): ConversionGoalFilter =>
    ({
        kind: NodeKind.EventsNode,
        event: 'purchase',
        name: 'Purchases',
        conversion_goal_id: GOAL_ID,
        conversion_goal_name: 'Purchases',
        schema_map: {},
    }) as ConversionGoalFilter

const otherGoal = (): ConversionGoalFilter =>
    ({
        kind: NodeKind.EventsNode,
        event: 'signed_up',
        name: 'Sign ups',
        conversion_goal_id: OTHER_GOAL_ID,
        conversion_goal_name: 'Sign ups',
        schema_map: {},
    }) as ConversionGoalFilter

describe('marketingRetentionLogic', () => {
    let logic: ReturnType<typeof marketingRetentionLogic.build>
    let settingsLogic: ReturnType<typeof marketingAnalyticsSettingsLogic.build>

    beforeEach(() => {
        initKeaTests()
        settingsLogic = marketingAnalyticsSettingsLogic()
        settingsLogic.mount()
        logic = marketingRetentionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        settingsLogic.unmount()
    })

    it('falls back to activity when conversion mode has no goal to count', () => {
        // A team with no usable conversion goal must still get a working tab. Sending
        // returningEvent=conversion_goal with no conversionGoalId fails the query outright.
        logic.actions.setReturningEvent(MarketingAnalyticsRetentionReturningEvent.ConversionGoal)

        const query = logic.values.query as MarketingAnalyticsRetentionQuery
        expect(query.returningEvent).toBe(MarketingAnalyticsRetentionReturningEvent.Activity)
        expect(query.conversionGoalId).toBeUndefined()
    })

    it('counts the goal once the team has a usable one', () => {
        // The other half of the fallback: with a goal available the query has to carry both the mode
        // and the id. Sending the mode without an id is the failing query the fallback exists to avoid.
        settingsLogic.actions.updateConversionGoals([eventGoal()])
        logic.actions.setReturningEvent(MarketingAnalyticsRetentionReturningEvent.ConversionGoal)

        const query = logic.values.query as MarketingAnalyticsRetentionQuery
        expect(query.returningEvent).toBe(MarketingAnalyticsRetentionReturningEvent.ConversionGoal)
        expect(query.conversionGoalId).toBe(GOAL_ID)
    })

    it('sends the two axes independently', () => {
        // The start and return goals are separate ids on the query. Collapsing them onto one would
        // quietly turn "who signed up, and did they buy" into "who bought, and did they buy again".
        settingsLogic.actions.updateConversionGoals([eventGoal(), otherGoal()])
        logic.actions.setStartEvent(MarketingAnalyticsRetentionStartEvent.ConversionGoal)
        logic.actions.setStartConversionGoalId(OTHER_GOAL_ID)
        logic.actions.setReturningEvent(MarketingAnalyticsRetentionReturningEvent.ConversionGoal)
        logic.actions.setConversionGoalId(GOAL_ID)

        const query = logic.values.query as MarketingAnalyticsRetentionQuery
        expect(query.startEvent).toBe(MarketingAnalyticsRetentionStartEvent.ConversionGoal)
        expect(query.startConversionGoalId).toBe(OTHER_GOAL_ID)
        expect(query.conversionGoalId).toBe(GOAL_ID)
    })

    it('falls back to arrival when the start mode has no goal to key off', () => {
        logic.actions.setStartEvent(MarketingAnalyticsRetentionStartEvent.ConversionGoal)

        const query = logic.values.query as MarketingAnalyticsRetentionQuery
        expect(query.startEvent).toBe(MarketingAnalyticsRetentionStartEvent.Arrival)
        expect(query.startConversionGoalId).toBeUndefined()
    })
})

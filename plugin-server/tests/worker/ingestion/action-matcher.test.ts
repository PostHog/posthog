import { DateTime } from 'luxon'

import {
    Action,
    ActionStep,
    Cohort,
    Element,
    Hub,
    ISOTimestamp,
    Person,
    PostIngestionEvent,
    PropertyOperator,
    RawAction,
    StringMatching,
    Team,
} from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { ActionManager } from '../../../src/worker/ingestion/action-manager'
import { ActionMatcher, castingCompare } from '../../../src/worker/ingestion/action-matcher'
import { commonUserId } from '../../helpers/plugins'
import { getFirstTeam, insertRow, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

/** Return a test event created on a common base using provided property overrides. */
function createTestEvent(overrides: Partial<PostIngestionEvent> = {}): PostIngestionEvent {
    const url: string = overrides.properties?.$current_url ?? 'http://example.com/foo/'
    return {
        eventUuid: 'uuid1',
        distinctId: 'my_id',
        ip: '127.0.0.1',
        teamId: 2,
        timestamp: new Date().toISOString() as ISOTimestamp,
        event: '$pageview',
        properties: { $current_url: url },
        elementsList: [],
        person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4C8',
        person_created_at: DateTime.fromSeconds(18000000).toISO() as ISOTimestamp,
        person_properties: {},
        ...overrides,
    }
}

describe('ActionMatcher', () => {
    let hub: Hub
    let actionManager: ActionManager
    let actionMatcher: ActionMatcher
    let actionCounter: number

    beforeEach(async () => {
        await resetTestDatabase(undefined, undefined, undefined, { withExtendedTestData: false })
        hub = await createHub()
        actionManager = new ActionManager(hub.db.postgres, hub)
        await actionManager.start()
        actionMatcher = new ActionMatcher(hub.db.postgres, actionManager, hub.teamManager)
        actionCounter = 0
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    /** Return a test action created on a common base using provided steps. */
    async function createTestAction(partialSteps: Partial<ActionStep>[] | null): Promise<Action> {
        const action: RawAction = {
            id: actionCounter++,
            team_id: 2,
            name: 'Test',
            description: '',
            created_at: new Date().toISOString(),
            created_by_id: commonUserId,
            deleted: false,
            post_to_slack: true,
            slack_message_format: '',
            is_calculating: false,
            updated_at: new Date().toISOString(),
            last_calculated_at: new Date().toISOString(),
            bytecode: null,
            bytecode_error: null,
            steps_json: partialSteps
                ? partialSteps.map(
                      (partialStep): ActionStep => ({
                          tag_name: null,
                          text: null,
                          text_matching: null,
                          href: null,
                          href_matching: null,
                          selector: null,
                          url: null,
                          url_matching: null,
                          event: null,
                          properties: null,
                          ...partialStep,
                      })
                  )
                : null,
        }
        await insertRow(hub.db.postgres, 'posthog_action', action)
        await actionManager.reloadAction(action.team_id, action.id)

        return {
            ...action,
            steps: action.steps_json ?? [],
            hooks: [],
        }
    }

    describe('#match()', () => {
        it('returns no match if action has no steps', async () => {
            await createTestAction(null)

            const event = createTestEvent()

            expect(await actionMatcher.match(event)).toEqual([])
        })

        it('returns a match in case of event property operator exact', async () => {
            const actionDefinitionOpExact: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 'bar', operator: 'exact' as PropertyOperator }],
                },
            ])
            const actionDefinitionOpUndefined: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 'bar' }], // undefined operator should mean "exact"
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of event property operator is not', async () => {
            const actionDefinitionOpIsNot: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 'bar', operator: 'is_not' as PropertyOperator }],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpIsNot])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpIsNot])
        })

        it('returns a match in case of event property operator contains', async () => {
            const actionDefinitionOpContains: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: 'bar', operator: 'icontains' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpContains])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of event property operator does not contain', async () => {
            const actionDefinitionOpNotContains: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: 'bar', operator: 'not_icontains' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpNotContains])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpNotContains])
        })

        it('returns a match in case of event property operator regex', async () => {
            const actionDefinitionOpRegex1: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: '^bar', operator: 'regex' as PropertyOperator }],
                },
            ])
            const actionDefinitionOpRegex2: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: '(?:.+bar|[A-Z])', operator: 'regex' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpRegex1])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpRegex1])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpRegex2])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([
                actionDefinitionOpRegex1,
                actionDefinitionOpRegex2,
            ])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpRegex2])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of event property operator not regex', async () => {
            const actionDefinitionOpNotRegex1: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', value: '^bar', operator: 'not_regex' as PropertyOperator },
                    ],
                },
            ])
            const actionDefinitionOpNotRegex2: Action = await createTestAction([
                {
                    properties: [
                        {
                            type: 'event',
                            key: 'foo',
                            value: '(?:.+bar|[A-Z])',
                            operator: 'not_regex' as PropertyOperator,
                        },
                    ],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpNotRegex2])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpNotRegex2])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpNotRegex1])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpNotRegex1])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
            expect(await actionMatcher.match(eventFooNull)).toEqual([
                actionDefinitionOpNotRegex1,
                actionDefinitionOpNotRegex2,
            ])
        })

        it('returns a match in case of event property operator is set', async () => {
            const actionDefinitionOpIsSet: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', operator: 'is_set' as PropertyOperator }],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpIsSet])
        })

        it('returns a match in case of event property operator is not set', async () => {
            const actionDefinitionOpIsNotSet: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', operator: 'is_not_set' as PropertyOperator }],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([actionDefinitionOpIsNotSet])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([actionDefinitionOpIsNotSet])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of event property operator greater than', async () => {
            const actionDefinitionOpGreaterThan: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 5, operator: 'gt' as PropertyOperator }],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumberMinusOne = createTestEvent({ properties: { foo: -1 } })
            const eventFooNumberFive = createTestEvent({ properties: { foo: 5 } })
            const eventFooNumberSevenNines = createTestEvent({ properties: { foo: 9999999 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberMinusOne)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberFive)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberSevenNines)).toEqual([actionDefinitionOpGreaterThan])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of event property operator less than', async () => {
            const actionDefinitionOpLessThan: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: 5, operator: 'lt' as PropertyOperator }],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: 'bar', pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooBarabara = createTestEvent({ properties: { foo: 'barabara' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumberMinusOne = createTestEvent({ properties: { foo: -1 } })
            const eventFooNumberFive = createTestEvent({ properties: { foo: 5 } })
            const eventFooNumberSevenNines = createTestEvent({ properties: { foo: 9999999 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooBarabara)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberMinusOne)).toEqual([actionDefinitionOpLessThan])
            expect(await actionMatcher.match(eventFooNumberFive)).toEqual([])
            expect(await actionMatcher.match(eventFooNumberSevenNines)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpLessThan]) // true is a 1
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('returns a match in case of URL contains page view', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: 'example.com',
                    url_matching: StringMatching.Contains,
                    event: '$pageview',
                },
            ])
            const actionDefinitionEmptyMatching: Action = await createTestAction([
                {
                    url: 'example.com',
                    url_matching: '' as StringMatching, // Empty url_matching should mean "contains"
                    event: '$pageview',
                },
            ])

            const eventPosthog = createTestEvent({
                properties: { $current_url: 'http://posthog.com/pricing' },
            })
            const eventExample = createTestEvent({
                properties: { $current_url: 'https://example.com/' },
            })

            expect(await actionMatcher.match(eventPosthog)).toEqual([])
            expect(await actionMatcher.match(eventExample)).toEqual([actionDefinition, actionDefinitionEmptyMatching])
        })

        it('returns a match in case of URL contains page views with % and _', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: 'exampl_.com/%.html',
                    url_matching: StringMatching.Contains,
                    event: '$pageview',
                },
            ])
            const actionDefinitionEmptyMatching: Action = await createTestAction([
                {
                    url: 'exampl_.com/%.html',
                    url_matching: '' as StringMatching, // Empty url_matching should mean "contains"
                    event: '$pageview',
                },
            ])

            const eventExample = createTestEvent({
                properties: { $current_url: 'https://example.com/' },
            })
            const eventExampleHtml = createTestEvent({
                properties: { $current_url: 'https://example.com/index.html' },
            })

            expect(await actionMatcher.match(eventExample)).toEqual([])
            expect(await actionMatcher.match(eventExampleHtml)).toEqual([
                actionDefinition,
                actionDefinitionEmptyMatching,
            ])
        })

        it('returns a match in case of URL matches regex page views', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: String.raw`^https?:\/\/example\.com\/\d+(\/[a-r]*\/?)?$`,
                    url_matching: StringMatching.Regex,
                    event: '$pageview',
                },
            ])

            const eventExampleOk1 = createTestEvent({
                properties: { $current_url: 'https://example.com/23/hello' },
            })
            const eventExampleOk2 = createTestEvent({
                properties: { $current_url: 'https://example.com/3/abc/' },
            })
            const eventExampleBad1 = createTestEvent({
                properties: { $current_url: 'https://example.com/3/xyz/' },
            })
            const eventExampleBad2 = createTestEvent({
                properties: { $current_url: 'https://example.com/' },
            })
            const eventExampleBad3 = createTestEvent({
                properties: { $current_url: 'https://example.com/uno/dos/' },
            })
            const eventExampleBad4 = createTestEvent({
                properties: { $current_url: 'https://example.com/1foo/' },
            })

            expect(await actionMatcher.match(eventExampleOk1)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleOk2)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad3)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad4)).toEqual([])
        })

        it('returns a match in case of URL matches exactly page views', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    url: 'https://www.mozilla.org/de/',
                    url_matching: StringMatching.Exact,
                    event: '$pageview',
                },
            ])

            const eventExampleOk = createTestEvent({
                properties: { $current_url: 'https://www.mozilla.org/de/' },
            })
            const eventExampleBad1 = createTestEvent({
                properties: { $current_url: 'https://www.mozilla.org/de' },
            })
            const eventExampleBad2 = createTestEvent({
                properties: { $current_url: 'https://www.mozilla.org/de/firefox/' },
            })

            expect(await actionMatcher.match(eventExampleOk)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
        })

        it('returns a match in case of exact event name', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    event: 'meow',
                },
            ])

            const eventExampleOk = createTestEvent({
                event: 'meow',
            })
            const eventExampleBad1 = createTestEvent({
                event: '$meow',
            })
            const eventExampleBad2 = createTestEvent({
                event: 'WOOF',
            })

            expect(await actionMatcher.match(eventExampleOk)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
        })

        it('returns a match in case of exact event name AND URL contains', async () => {
            const actionDefinition: Action = await createTestAction([
                {
                    event: 'meow',
                    url_matching: StringMatching.Contains,
                    url: 'pets.com/',
                },
            ])

            const eventExampleOk1 = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'http://www.pets.com/' },
            })
            const eventExampleOk2 = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'https://pets.com/food' },
            })
            const eventExampleBad1 = createTestEvent({
                event: '$meow',
                properties: { $current_url: 'https://xyz.pets.com/' },
            })
            const eventExampleBad2 = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'https://www.pets.com.de/' },
            })
            const eventExampleBad3 = createTestEvent({
                event: 'meow',
                properties: { $current_url: 'https://www.pets.co' },
            })

            expect(await actionMatcher.match(eventExampleOk1)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleOk2)).toEqual([actionDefinition])
            expect(await actionMatcher.match(eventExampleBad1)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad2)).toEqual([])
            expect(await actionMatcher.match(eventExampleBad3)).toEqual([])
        })

        it('returns a match in case of person property operator exact', async () => {
            const actionDefinitionOpExact: Action = await createTestAction([
                {
                    properties: [{ type: 'person', key: 'foo', value: 'bar', operator: 'exact' as PropertyOperator }],
                },
            ])
            const actionDefinitionOpUndefined: Action = await createTestAction([
                {
                    properties: [{ type: 'person', key: 'foo', value: 'bar' }], // undefined operator should mean "exact"
                },
            ])

            const event = createTestEvent()

            expect(await actionMatcher.match({ ...event, person_properties: { foo: 'bar' } })).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: 'bar', pol: 'pot' } })).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: 'baR' } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: 'baz' } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: 'barabara' } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: 'rabarbar' } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: 7 } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: {} })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { something_else: 999 } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: true } })).toEqual([])
            expect(await actionMatcher.match({ ...event, person_properties: { foo: null } })).toEqual([])
        })

        it('returns a match in case of cohort match', async () => {
            const testCohort = await hub.db.createCohort({
                name: 'Test',
                description: 'Test',
                created_by_id: commonUserId,
                team_id: 2,
            })

            const actionDefinition: Action = await createTestAction([
                {
                    properties: [{ type: 'cohort', key: 'id', value: testCohort.id }],
                },
            ])
            const actionDefinitionAllUsers: Action = await createTestAction([
                {
                    properties: [{ type: 'cohort', key: 'id', value: 'all' }],
                },
            ])

            const nonCohortPerson = await hub.db.createPerson(
                DateTime.local(),
                {},
                {},
                {},
                actionDefinition.team_id,
                null,
                true,
                new UUIDT().toString(),
                [{ distinctId: 'random' }]
            )

            const cohortPerson = await hub.db.createPerson(
                DateTime.local(),
                {},
                {},
                {},
                actionDefinition.team_id,
                null,
                true,
                new UUIDT().toString(),
                [{ distinctId: 'cohort' }]
            )
            await hub.db.addPersonToCohort(testCohort.id, cohortPerson.id, testCohort.version)

            const eventExamplePersonBad = createTestEvent({
                event: 'meow',
                distinctId: 'random',
                person_id: nonCohortPerson.uuid,
            })
            const eventExamplePersonOk = createTestEvent({
                event: 'meow',
                distinctId: 'cohort',
                person_id: cohortPerson.uuid,
            })
            const eventExamplePersonUnknown = createTestEvent({
                event: 'meow',
                distinctId: 'unknown',
                person_id: undefined,
            })

            expect(await actionMatcher.match(eventExamplePersonOk)).toEqual([
                actionDefinition,
                actionDefinitionAllUsers,
            ])
            expect(await actionMatcher.match(eventExamplePersonBad)).toEqual([actionDefinitionAllUsers])
            expect(await actionMatcher.match(eventExamplePersonUnknown)).toEqual([actionDefinitionAllUsers])
        })

        it('returns a match in case of element href equals', async () => {
            const actionDefinitionLinkHref: Action = await createTestAction([
                {
                    href: 'https://example.com/',
                },
            ])

            const event = createTestEvent()
            const elementsHrefOuter: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefInner: Element[] = [
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsNoHref: Element[] = [
                { tag_name: 'span' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefOuter })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefInner })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsNoHref })).toEqual([])
        })

        it('returns a match in case of element href contains', async () => {
            const actionDefinitionLinkHref: Action = await createTestAction([
                {
                    href: 'https://example.com/',
                    href_matching: StringMatching.Contains,
                },
            ])

            const event = createTestEvent()
            const elementsExactHrefOuter: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsExactHrefInner: Element[] = [
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsExtendedHref: Element[] = [
                { tag_name: 'a', href: 'https://example.com/foobar' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsBadHref: Element[] = [
                { tag_name: 'a', href: 'https://example.io/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsNoHref: Element[] = [
                { tag_name: 'span' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsExactHrefOuter })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsExactHrefInner })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsExtendedHref })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsBadHref })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsNoHref })).toEqual([])
        })

        it('returns a match in case of element href contains, with wildcard', async () => {
            const actionDefinitionLinkHref: Action = await createTestAction([
                {
                    href: 'https://example.com/%bar',
                    href_matching: StringMatching.Contains,
                },
            ])

            const event = createTestEvent()
            const elementsExactHrefOuter: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsExactHrefInner: Element[] = [
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsExtendedHref: Element[] = [
                { tag_name: 'a', href: 'https://example.com/foobar' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsBadHref: Element[] = [
                { tag_name: 'a', href: 'https://example.io/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsNoHref: Element[] = [
                { tag_name: 'span' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsExactHrefOuter })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsExactHrefInner })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsExtendedHref })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsBadHref })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsNoHref })).toEqual([])
        })

        it('returns a match in case of element href matches regex', async () => {
            const actionDefinitionLinkHref: Action = await createTestAction([
                {
                    href: 'https://example.com/.*(?:bar|baz)',
                    href_matching: StringMatching.Regex,
                },
            ])

            const event = createTestEvent()
            const elementsExactHrefOuter: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsExactHrefInner: Element[] = [
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsExtendedHref: Element[] = [
                { tag_name: 'a', href: 'https://example.com/foobar' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsBadHref: Element[] = [
                { tag_name: 'a', href: 'https://example.io/' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]
            const elementsNoHref: Element[] = [
                { tag_name: 'span' },
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsExactHrefOuter })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsExactHrefInner })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsExtendedHref })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsBadHref })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsNoHref })).toEqual([])
        })

        it('returns a match in case of element text and tag name equals', async () => {
            const actionDefinitionLinkHref: Action = await createTestAction([
                {
                    tag_name: 'h1',
                    text: 'Hallo!',
                },
            ])

            const event = createTestEvent()
            const elementsHrefProper: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'], text: 'Hallo!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefWrongTag: Element[] = [
                { tag_name: 'h3', attr_class: ['headline'], text: 'Hallo!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefWrongText: Element[] = [
                { tag_name: 'h3', attr_class: ['headline'], text: 'Auf Wiedersehen!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefWrongLevel: Element[] = [
                { tag_name: 'i', attr_class: ['headline'], text: 'Auf Wiedersehen!' },
                { tag_name: 'h1' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefProper })).toEqual([
                actionDefinitionLinkHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefWrongTag })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefWrongText })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefWrongLevel })).toEqual([])
        })

        it('returns a match in case of element text contains', async () => {
            const actionDefinitionLinkHref: Action = await createTestAction([
                {
                    text: 'Wieder',
                    text_matching: StringMatching.Contains,
                },
            ])

            const event = createTestEvent()
            const elementsHrefBadText: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'], text: 'Hallo!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefGoodText: Element[] = [
                { tag_name: 'h3', attr_class: ['headline'], text: 'Auf Wiedersehen!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefBadText })).toEqual([])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefGoodText })).toEqual([
                actionDefinitionLinkHref,
            ])
        })

        it('returns a match in case of element selector', async () => {
            const actionDefinitionAnyDescendant: Action = await createTestAction([
                {
                    selector: 'main h1.headline',
                },
            ])
            const actionDefinitionDirectDescendant: Action = await createTestAction([
                {
                    selector: 'main > h1.headline',
                },
            ])
            const actionDefinitionDirectHref: Action = await createTestAction([
                {
                    selector: 'main > a[href="https://example.com/"]',
                },
            ])
            const actionDefinitionArraySelectorProp: Action = await createTestAction([
                {
                    properties: [{ type: 'element', key: 'selector', value: ['main h1.headline'] }],
                },
            ])

            const event = createTestEvent()
            const elementsHrefProperNondirect: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'], text: 'Hallo!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefWrongClassNondirect: Element[] = [
                { tag_name: 'h1', attr_class: ['oof'], text: 'Hallo!' },
                { tag_name: 'a', href: 'https://example.com/' },
                { tag_name: 'main' },
            ]
            const elementsHrefProperDirect: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'], text: 'Hallo!' },
                { tag_name: 'main' },
            ]

            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefProperNondirect })).toEqual([
                actionDefinitionAnyDescendant,
                actionDefinitionDirectHref,
                actionDefinitionArraySelectorProp,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefWrongClassNondirect })).toEqual([
                actionDefinitionDirectHref,
            ])
            expect(await actionMatcher.match({ ...event, elementsList: elementsHrefProperDirect })).toEqual([
                actionDefinitionAnyDescendant,
                actionDefinitionDirectDescendant,
                actionDefinitionArraySelectorProp,
            ])
        })

        it('returns a match using filter value casting, with multiple match groups', async () => {
            const actionDefinition: Action = await createTestAction([
                { event: 'tenet' },
                {
                    properties: [
                        { key: 'insight', type: 'event', value: ['STICKINESS'], operator: PropertyOperator.Exact },
                        {
                            key: 'total_event_action_filters_count',
                            type: 'event',
                            value: '0',
                            operator: PropertyOperator.Exact,
                        },
                        {
                            key: 'total_event_actions_count',
                            type: 'event',
                            value: '0',
                            operator: PropertyOperator.GreaterThan,
                        },
                    ],
                },
            ])

            const eventExampleOk1 = createTestEvent({
                event: 'meow',
                properties: {
                    insight: 'STICKINESS',
                    total_event_action_filters_count: 0,
                    total_event_actions_count: 4,
                },
            })

            expect(await actionMatcher.match(eventExampleOk1)).toEqual([actionDefinition])
        })

        it('properly handles is_not null string coercion', async () => {
            const actionDefinitionOpIsSet: Action = await createTestAction([
                {
                    properties: [
                        { type: 'event', key: 'foo', operator: 'is_set' as PropertyOperator },
                        { type: 'event', key: 'foo', value: ['null'], operator: 'is_not' as PropertyOperator },
                    ],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: null, pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooNull)).toEqual([])
        })

        it('properly handles exact null string coercion', async () => {
            const actionDefinitionOpIsSet: Action = await createTestAction([
                {
                    properties: [{ type: 'event', key: 'foo', value: ['null'] }],
                },
            ])

            const eventFooBar = createTestEvent({ properties: { foo: 'bar' } })
            const eventFooBarPolPot = createTestEvent({ properties: { foo: null, pol: 'pot' } })
            const eventFooBaR = createTestEvent({ properties: { foo: 'baR' } })
            const eventFooBaz = createTestEvent({ properties: { foo: 'baz' } })
            const eventFooRabarbar = createTestEvent({ properties: { foo: 'rabarbar' } })
            const eventFooNumber = createTestEvent({ properties: { foo: 7 } })
            const eventNoNothing = createTestEvent()
            const eventFigNumber = createTestEvent({ properties: { fig: 999 } })
            const eventFooTrue = createTestEvent({ properties: { foo: true } })
            const eventFooNull = createTestEvent({ properties: { foo: null } })

            expect(await actionMatcher.match(eventFooBar)).toEqual([])
            expect(await actionMatcher.match(eventFooBarPolPot)).toEqual([actionDefinitionOpIsSet])
            expect(await actionMatcher.match(eventFooBaR)).toEqual([])
            expect(await actionMatcher.match(eventFooBaz)).toEqual([])
            expect(await actionMatcher.match(eventFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(eventFooNumber)).toEqual([])
            expect(await actionMatcher.match(eventNoNothing)).toEqual([])
            expect(await actionMatcher.match(eventFigNumber)).toEqual([])
            expect(await actionMatcher.match(eventFooTrue)).toEqual([])
            expect(await actionMatcher.match(eventFooNull)).toEqual([actionDefinitionOpIsSet])
        })
    })

    describe('#checkElementsAgainstSelector()', () => {
        const checkElementsAgainstSelector = (elements: Element[], selector: string): boolean => {
            return actionMatcher.checkElementsAgainstSelector(
                { elementsList: elements } as PostIngestionEvent,
                selector
            )
        }

        it('handles selector with attribute', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'], attributes: { 'attr__data-attr': 'xyz' } },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'div' },
                { tag_name: 'main' },
            ]

            expect(checkElementsAgainstSelector(elements, "[data-attr='xyz']")).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, "h1[data-attr='xyz']")).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, ".headline[data-attr='xyz']")).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, "main [data-attr='xyz']")).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, ".top [data-attr='xyz']")).toBeTruthy()

            expect(checkElementsAgainstSelector(elements, "[data-attr='foo']")).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, "main[data-attr='xyz']")).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, "div[data-attr='xyz']")).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, "div[data-attr='xyz']")).toBeFalsy()
        })

        it('handles any descendant selector', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'main' },
            ]

            expect(checkElementsAgainstSelector(elements, 'main h1')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'main .headline')).toBeTruthy()

            expect(checkElementsAgainstSelector(elements, 'h1 div')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, '.top main')).toBeFalsy()

            expect(checkElementsAgainstSelector(elements, 'main div')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'main .top')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'div h1')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'div .headline')).toBeTruthy()
        })

        it('handles direct descendant selector', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'main' },
            ]

            expect(checkElementsAgainstSelector(elements, 'main > h1')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, 'main > .headline')).toBeFalsy()

            expect(checkElementsAgainstSelector(elements, 'main > .top > h1')).toBeTruthy()

            expect(checkElementsAgainstSelector(elements, 'h1 > div')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, '.top > main')).toBeFalsy()

            expect(checkElementsAgainstSelector(elements, 'main > div')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'main > .top')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'div > h1')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'div > .headline')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 1', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['inner'] },
                { tag_name: 'div', attr_class: ['outer'] },
                { tag_name: 'main' },
            ]

            expect(checkElementsAgainstSelector(elements, 'main > h1')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, 'main > .inner')).toBeFalsy()

            expect(checkElementsAgainstSelector(elements, 'main > .outer > .inner > h1')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'main > .inner > h1')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, 'main > .outer > h1')).toBeFalsy()

            expect(checkElementsAgainstSelector(elements, 'h1 > div')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, 'outer > main')).toBeFalsy()

            expect(checkElementsAgainstSelector(elements, 'main > div')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'main > .outer')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'div > h1')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, '.inner > .headline')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 2', () => {
            const elements: Element[] = [
                { tag_name: 'span' },
                { tag_name: 'div' },
                { tag_name: 'a' },
                { tag_name: 'div' },
                { tag_name: 'div' },
                { tag_name: 'aside' },
                { tag_name: 'section' },
            ]

            expect(checkElementsAgainstSelector(elements, 'aside div > span')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 3', () => {
            const elements: Element[] = [{ tag_name: 'span', nth_child: 2, nth_of_type: 1 }, { tag_name: 'section' }]

            expect(checkElementsAgainstSelector(elements, 'section > span:nth-child(2):nth-of-type(1)')).toBeTruthy()
            expect(checkElementsAgainstSelector(elements, 'section > span:nth-child(1):nth-of-type(1)')).toBeFalsy()
            expect(checkElementsAgainstSelector(elements, 'section > span:nth-child(2):nth-of-type(3)')).toBeFalsy()
        })
    })

    describe('doesPersonBelongToCohort()', () => {
        let team: Team
        let cohort: Cohort
        let person: Person
        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            cohort = await hub.db.createCohort({
                name: 'testCohort',
                description: '',
                team_id: team.id,
                version: 10,
            })
            person = await hub.db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, false, new UUIDT().toString(), [])
        })

        it('returns false if person does not belong to cohort', async () => {
            const cohort2 = await hub.db.createCohort({
                name: 'testCohort2',
                description: '',
                team_id: team.id,
            })
            await hub.db.addPersonToCohort(cohort2.id, person.id, cohort.version)

            expect(await actionMatcher.doesPersonBelongToCohort(cohort.id, person.uuid, person.team_id)).toEqual(false)
        })

        it('returns true if person belongs to cohort', async () => {
            await hub.db.addPersonToCohort(cohort.id, person.id, cohort.version)

            expect(await actionMatcher.doesPersonBelongToCohort(cohort.id, person.uuid, person.team_id)).toEqual(true)
        })

        it('returns false if person does not belong to current version of the cohort', async () => {
            await hub.db.addPersonToCohort(cohort.id, person.id, -1)

            expect(await actionMatcher.doesPersonBelongToCohort(cohort.id, person.uuid, person.team_id)).toEqual(false)
        })

        it('handles NULL version cohorts', async () => {
            const cohort2 = await hub.db.createCohort({
                name: 'null_cohort',
                description: '',
                team_id: team.id,
                version: null,
            })
            expect(await actionMatcher.doesPersonBelongToCohort(cohort2.id, person.uuid, person.team_id)).toEqual(false)

            await hub.db.addPersonToCohort(cohort2.id, person.id, null)
            expect(await actionMatcher.doesPersonBelongToCohort(cohort2.id, person.uuid, person.team_id)).toEqual(true)
        })
    })
})

describe('castingCompare', () => {
    it('compares exact', () => {
        expect(castingCompare(2, '2', PropertyOperator.Exact)).toBeTruthy()
        expect(castingCompare('2', 2, PropertyOperator.Exact)).toBeTruthy()
        expect(castingCompare(true, 'true', PropertyOperator.Exact)).toBeTruthy()
        expect(castingCompare(true, true, PropertyOperator.Exact)).toBeTruthy()
        expect(castingCompare('90', '90', PropertyOperator.Exact)).toBeTruthy()
        expect(castingCompare('1', true, PropertyOperator.Exact)).toBeTruthy()

        expect(castingCompare('1', 'true', PropertyOperator.Exact)).toBeFalsy()
        expect(castingCompare('1', false, PropertyOperator.Exact)).toBeFalsy()
        expect(castingCompare(false, '1', PropertyOperator.Exact)).toBeFalsy()
        expect(castingCompare(false, 'true', PropertyOperator.Exact)).toBeFalsy()
    })
    it('compares less than', () => {
        expect(castingCompare(2, '2', PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare('2', 2, PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare('1', 'true', PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare('0', 'true', PropertyOperator.Exact)).toBeFalsy()
        expect(castingCompare(true, 'true', PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare(true, true, PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare('90', '90', PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare('1', true, PropertyOperator.LessThan)).toBeFalsy()
        expect(castingCompare('1', false, PropertyOperator.LessThan)).toBeFalsy()

        expect(castingCompare(false, '1', PropertyOperator.LessThan)).toBeTruthy()
        expect(castingCompare(false, 'true', PropertyOperator.LessThan)).toBeTruthy()
        expect(castingCompare('2', 3, PropertyOperator.LessThan)).toBeTruthy()
        expect(castingCompare('445.3', 9099.2, PropertyOperator.LessThan)).toBeTruthy()
    })
    it('compares greater than', () => {
        expect(castingCompare(2, '2', PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('2', 2, PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('1', 'true', PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('1', 'false', PropertyOperator.Exact)).toBeFalsy()
        expect(castingCompare(true, 'true', PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare(true, true, PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('90', '90', PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('1', true, PropertyOperator.GreaterThan)).toBeFalsy()

        expect(castingCompare(false, '1', PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare(false, 'true', PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('2', 3, PropertyOperator.GreaterThan)).toBeFalsy()
        expect(castingCompare('445.3', 9099.2, PropertyOperator.GreaterThan)).toBeFalsy()

        expect(castingCompare('1', false, PropertyOperator.GreaterThan)).toBeTruthy()
        expect(castingCompare(true, '-1', PropertyOperator.GreaterThan)).toBeTruthy()
        expect(castingCompare(1, 'false', PropertyOperator.GreaterThan)).toBeTruthy()
        expect(castingCompare(333, '2', PropertyOperator.GreaterThan)).toBeTruthy()
        expect(castingCompare('9032.3', -1.2, PropertyOperator.GreaterThan)).toBeTruthy()
    })
})

import { DateTime } from 'luxon'

import {
    Action,
    ActionStep,
    ActionStepUrlMatching,
    Element,
    Hub,
    Person,
    PreIngestionEvent,
    PropertyOperator,
    RawAction,
} from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { ActionMatcher, castingCompare } from '../../../src/worker/ingestion/action-matcher'
import { commonUserId } from '../../helpers/plugins'
import { insertRow, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

describe('ActionMatcher', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let actionMatcher: ActionMatcher
    let actionCounter: number

    beforeEach(async () => {
        await resetTestDatabase(undefined, undefined, undefined, { withExtendedTestData: false })
        ;[hub, closeServer] = await createHub()
        actionMatcher = hub.actionMatcher
        actionCounter = 0
    })

    afterEach(async () => {
        await closeServer()
    })

    /** Return a test action created on a common base using provided steps. */
    async function createTestAction(partialSteps: Partial<ActionStep>[]): Promise<Action> {
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
        }
        const steps: ActionStep[] = partialSteps.map(
            (partialStep, index) =>
                ({
                    id: action.id * 100 + index,
                    action_id: action.id,
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    name: null,
                    event: null,
                    properties: null,
                    ...partialStep,
                } as ActionStep)
        )
        await insertRow(hub.db.postgres, 'posthog_action', action)
        await Promise.all(steps.map((step) => insertRow(hub.db.postgres, 'posthog_actionstep', step)))
        await hub.actionManager.reloadAction(action.team_id, action.id)
        return { ...action, steps, hooks: [] }
    }

    /** Return a test event created on a common base using provided property overrides. */
    function createTestEvent(overrides: Partial<PreIngestionEvent> = {}): PreIngestionEvent {
        const url: string = overrides.properties?.$current_url ?? 'http://example.com/foo/'
        return {
            eventUuid: 'uuid1',
            distinctId: 'my_id',
            ip: '127.0.0.1',
            teamId: 2,
            timestamp: new Date().toISOString(),
            event: '$pageview',
            properties: { $current_url: url },
            elementsList: [],
            ...overrides,
        }
    }

    /** Return a test person created on a common base using provided property overrides. */
    function createTestPerson(overrides: Partial<Person> = {}): Person {
        return {
            id: 2,
            team_id: 2,
            properties: {},
            is_user_id: 0,
            is_identified: true,
            uuid: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4C8',
            created_at: DateTime.fromSeconds(18000000),
            version: 0,
            ...overrides,
        }
    }

    describe('#match()', () => {
        it('returns no match if action has no steps', async () => {
            await createTestAction([])

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
                    url_matching: ActionStepUrlMatching.Contains,
                    event: '$pageview',
                },
            ])
            const actionDefinitionEmptyMatching: Action = await createTestAction([
                {
                    url: 'example.com',
                    url_matching: '' as ActionStepUrlMatching, // Empty url_matching should mean "contains"
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
                    url_matching: ActionStepUrlMatching.Contains,
                    event: '$pageview',
                },
            ])
            const actionDefinitionEmptyMatching: Action = await createTestAction([
                {
                    url: 'exampl_.com/%.html',
                    url_matching: '' as ActionStepUrlMatching, // Empty url_matching should mean "contains"
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
                    url_matching: ActionStepUrlMatching.Regex,
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
                    url_matching: ActionStepUrlMatching.Exact,
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
                    url_matching: ActionStepUrlMatching.Contains,
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

            const personFooBar = createTestPerson({ properties: { foo: 'bar' } })
            const personFooBarPolPot = createTestPerson({ properties: { foo: 'bar', pol: 'pot' } })
            const personFooBaR = createTestPerson({ properties: { foo: 'baR' } })
            const personFooBaz = createTestPerson({ properties: { foo: 'baz' } })
            const personFooBarabara = createTestPerson({ properties: { foo: 'barabara' } })
            const personFooRabarbar = createTestPerson({ properties: { foo: 'rabarbar' } })
            const personFooNumber = createTestPerson({ properties: { foo: 7 } })
            const personNoNothing = createTestPerson()
            const personFigNumber = createTestPerson({ properties: { fig: 999 } })
            const personFooTrue = createTestPerson({ properties: { foo: true } })
            const personFooNull = createTestPerson({ properties: { foo: null } })

            expect(await actionMatcher.match(event, personFooBar)).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match(event, personFooBarPolPot)).toEqual([
                actionDefinitionOpExact,
                actionDefinitionOpUndefined,
            ])
            expect(await actionMatcher.match(event, personFooBaR)).toEqual([])
            expect(await actionMatcher.match(event, personFooBaz)).toEqual([])
            expect(await actionMatcher.match(event, personFooBarabara)).toEqual([])
            expect(await actionMatcher.match(event, personFooRabarbar)).toEqual([])
            expect(await actionMatcher.match(event, personFooNumber)).toEqual([])
            expect(await actionMatcher.match(event, personNoNothing)).toEqual([])
            expect(await actionMatcher.match(event, personFigNumber)).toEqual([])
            expect(await actionMatcher.match(event, personFooTrue)).toEqual([])
            expect(await actionMatcher.match(event, personFooNull)).toEqual([])
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

            const cohortPerson = await hub.db.createPerson(
                DateTime.local(),
                {},
                actionDefinition.team_id,
                null,
                true,
                new UUIDT().toString(),
                ['cohort']
            )
            await hub.db.addPersonToCohort(testCohort.id, cohortPerson.id, testCohort.version)

            const eventExamplePersonBad = createTestEvent({
                event: 'meow',
                distinctId: 'random',
            })
            const eventExamplePersonOk = createTestEvent({
                event: 'meow',
                distinctId: 'cohort',
            })
            const eventExamplePersonUnknown = createTestEvent({
                event: 'meow',
                distinctId: 'unknown',
            })

            expect(
                await actionMatcher.match(
                    eventExamplePersonOk,
                    await hub.db.fetchPerson(actionDefinition.team_id, eventExamplePersonOk.distinctId)
                )
            ).toEqual([actionDefinition, actionDefinitionAllUsers])
            expect(
                await actionMatcher.match(
                    eventExamplePersonBad,
                    await hub.db.fetchPerson(actionDefinition.team_id, eventExamplePersonBad.distinctId)
                )
            ).toEqual([actionDefinitionAllUsers])
            expect(
                await actionMatcher.match(
                    eventExamplePersonUnknown,
                    await hub.db.fetchPerson(actionDefinition.team_id, eventExamplePersonUnknown.distinctId)
                )
            ).toEqual([actionDefinitionAllUsers])
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

            expect(await actionMatcher.match(event, undefined, elementsHrefOuter)).toEqual([actionDefinitionLinkHref])
            expect(await actionMatcher.match(event, undefined, elementsHrefInner)).toEqual([actionDefinitionLinkHref])
            expect(await actionMatcher.match(event, undefined, elementsNoHref)).toEqual([])
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

            expect(await actionMatcher.match(event, undefined, elementsHrefProper)).toEqual([actionDefinitionLinkHref])
            expect(await actionMatcher.match(event, undefined, elementsHrefWrongTag)).toEqual([])
            expect(await actionMatcher.match(event, undefined, elementsHrefWrongText)).toEqual([])
            expect(await actionMatcher.match(event, undefined, elementsHrefWrongLevel)).toEqual([])
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

            expect(await actionMatcher.match(event, undefined, elementsHrefProperNondirect)).toEqual([
                actionDefinitionAnyDescendant,
                actionDefinitionDirectHref,
                actionDefinitionArraySelectorProp,
            ])
            expect(await actionMatcher.match(event, undefined, elementsHrefWrongClassNondirect)).toEqual([
                actionDefinitionDirectHref,
            ])
            expect(await actionMatcher.match(event, undefined, elementsHrefProperDirect)).toEqual([
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
        it('handles selector with attribute', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'], attributes: { 'attr__data-attr': 'xyz' } },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'div' },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, "[data-attr='xyz']")).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, "h1[data-attr='xyz']")).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, ".headline[data-attr='xyz']")).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, "main [data-attr='xyz']")).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, ".top [data-attr='xyz']")).toBeTruthy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, "[data-attr='foo']")).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, "main[data-attr='xyz']")).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, "div[data-attr='xyz']")).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, "div[data-attr='xyz']")).toBeFalsy()
        })

        it('handles any descendant selector', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main .headline')).toBeTruthy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'h1 div')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, '.top main')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main div')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main .top')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div .headline')).toBeTruthy()
        })

        it('handles direct descendant selector', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['top'] },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > h1')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .headline')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .top > h1')).toBeTruthy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'h1 > div')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, '.top > main')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > div')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .top')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div > h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div > .headline')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 1', () => {
            const elements: Element[] = [
                { tag_name: 'h1', attr_class: ['headline'] },
                { tag_name: 'div', attr_class: ['inner'] },
                { tag_name: 'div', attr_class: ['outer'] },
                { tag_name: 'main' },
            ]

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > h1')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .inner')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .outer > .inner > h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .inner > h1')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .outer > h1')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'h1 > div')).toBeFalsy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'outer > main')).toBeFalsy()

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > div')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'main > .outer')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, 'div > h1')).toBeTruthy()
            expect(actionMatcher.checkElementsAgainstSelector(elements, '.inner > .headline')).toBeTruthy()
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

            expect(actionMatcher.checkElementsAgainstSelector(elements, 'aside div > span')).toBeTruthy()
        })

        it('handles direct descendant selector edge cases 3', () => {
            const elements: Element[] = [{ tag_name: 'span', nth_child: 2, nth_of_type: 1 }, { tag_name: 'section' }]

            expect(
                actionMatcher.checkElementsAgainstSelector(elements, 'section > span:nth-child(2):nth-of-type(1)')
            ).toBeTruthy()
            expect(
                actionMatcher.checkElementsAgainstSelector(elements, 'section > span:nth-child(1):nth-of-type(1)')
            ).toBeFalsy()
            expect(
                actionMatcher.checkElementsAgainstSelector(elements, 'section > span:nth-child(2):nth-of-type(3)')
            ).toBeFalsy()
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

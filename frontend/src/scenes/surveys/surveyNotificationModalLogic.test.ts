import { NEW_SURVEY } from 'scenes/surveys/constants'

import { NodeKind } from '~/queries/schema/schema-general'
import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
} from '~/types'

import {
    alignGlobalsWithNotificationFilter,
    buildLastSurveyResponseQuery,
    getDefaultSurveyMessage,
    remapSurveyResponseProperties,
} from './surveyNotificationModalLogic'
import { buildSurveyExampleInvocationGlobals } from './utils'

describe('surveyNotificationModalLogic', () => {
    it('includes survey status text in the default notification message', () => {
        expect(
            getDefaultSurveyMessage([
                {
                    id: 'question-1',
                    question: 'What can we improve?',
                    type: SurveyQuestionType.Open,
                },
            ])
        ).toEqual(`*Survey update on {event.properties['$survey_name']}*
{event.event == 'survey dismissed' ? (event.properties['$survey_partially_completed'] ? 'Dismissed after a partial response' : 'Dismissed before completion') : 'Completed response'}
{person.name} · {person.properties.email}

*Responses*
- What can we improve?: {event.properties['$survey_response_question-1']}`)
    })

    it('remaps copied survey response properties to the target survey questions by order', () => {
        const copiedInputs = {
            text: {
                value: "First: {event.properties['$survey_response_source-a']} second: {event.properties['$survey_response_source-b']}",
            },
            body: {
                value: {
                    '$survey_response_source-a': "{event.properties['$survey_response_source-a']}",
                    nested: ["{event.properties['$survey_response_source-b']}"],
                },
            },
        }

        expect(
            remapSurveyResponseProperties(copiedInputs, {
                id: 'target-survey',
                name: 'Target survey',
                enable_partial_responses: true,
                questions: [
                    { id: 'target-a', question: 'First?', type: SurveyQuestionType.Open },
                    { id: 'target-b', question: 'Second?', type: SurveyQuestionType.Open },
                ],
            })
        ).toEqual({
            text: {
                value: "First: {event.properties['$survey_response_target-a']} second: {event.properties['$survey_response_target-b']}",
            },
            body: {
                value: {
                    '$survey_response_target-a': "{event.properties['$survey_response_target-a']}",
                    nested: ["{event.properties['$survey_response_target-b']}"],
                },
            },
        })
    })

    it.each([NEW_SURVEY.id, ''])('returns no query when building a last-response lookup for survey id "%s"', (id) => {
        expect(buildLastSurveyResponseQuery(id, null)).toBeNull()
    })

    it('builds a last-response events query scoped to the survey when the notification has no filters', () => {
        const query = buildLastSurveyResponseQuery('survey-abc', null)
        expect(query).toMatchObject({
            kind: NodeKind.EventsQuery,
            select: ['*', 'person'],
            limit: 1,
            after: '-90d',
            orderBy: ['timestamp DESC'],
            events: [SurveyEventName.SENT, SurveyEventName.DISMISSED],
        })
        expect(query?.fixedProperties).toEqual([
            {
                key: SurveyEventProperties.SURVEY_ID,
                type: PropertyFilterType.Event,
                value: 'survey-abc',
                operator: PropertyOperator.Exact,
            },
        ])
    })

    it('requires the last response to match one of the notification event filters', () => {
        const completedFilter: EventPropertyFilter = {
            key: SurveyEventProperties.SURVEY_COMPLETED,
            type: PropertyFilterType.Event,
            value: true,
            operator: PropertyOperator.Exact,
        }
        const ratingFilter: EventPropertyFilter = {
            key: '$survey_response_question-1',
            type: PropertyFilterType.Event,
            value: 8,
            operator: PropertyOperator.GreaterThanOrEqual,
        }
        const globalFilter: EventPropertyFilter = {
            key: '$browser',
            type: PropertyFilterType.Event,
            value: 'Chrome',
            operator: PropertyOperator.Exact,
        }

        const query = buildLastSurveyResponseQuery('survey-abc', {
            events: [
                { id: SurveyEventName.SENT, type: 'events', properties: [completedFilter, ratingFilter] },
                { id: SurveyEventName.DISMISSED, type: 'events', properties: [] },
            ],
            properties: [globalFilter],
            filter_test_accounts: true,
        })

        expect(query?.event).toBeUndefined()
        expect(query?.events).toBeUndefined()
        expect(query?.filterTestAccounts).toBe(true)
        expect(query?.fixedProperties).toEqual([
            {
                key: SurveyEventProperties.SURVEY_ID,
                type: PropertyFilterType.Event,
                value: 'survey-abc',
                operator: PropertyOperator.Exact,
            },
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.Or,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    completedFilter,
                                    ratingFilter,
                                    { type: PropertyFilterType.HogQL, key: "event = 'survey sent'" },
                                ],
                            },
                            {
                                type: FilterLogicalOperator.And,
                                values: [{ type: PropertyFilterType.HogQL, key: "event = 'survey dismissed'" }],
                            },
                        ],
                    },
                    { type: FilterLogicalOperator.And, values: [globalFilter] },
                ],
            },
        ])
    })

    it.each([
        [
            'copies an exact value the sample is missing',
            { key: '$browser', operator: PropertyOperator.Exact, value: 'Chrome' },
            'Chrome',
        ],
        [
            'copies the first accepted value of an is-any-of filter',
            { key: '$survey_response_q1', operator: PropertyOperator.Exact, value: ['Other', 'Bug'] },
            'Other',
        ],
        [
            'leaves the sample alone for a negated filter',
            { key: '$survey_response_q1', operator: PropertyOperator.IsNot, value: 'Other' },
            // The example globals answer an open question with its own text.
            'What could be better?',
        ],
    ])('aligning sample globals with the notification filter %s', (_name, property, expected) => {
        const globals = buildSurveyExampleInvocationGlobals({
            survey: {
                id: 'survey-abc',
                name: 'Survey',
                questions: [{ id: 'q1', question: 'What could be better?', type: SurveyQuestionType.Open }],
            },
            projectId: 1,
            projectName: 'Project',
            projectUrl: 'https://example.com/project/1',
        })

        const aligned = alignGlobalsWithNotificationFilter(globals, {
            events: [
                {
                    id: SurveyEventName.SENT,
                    type: 'events',
                    properties: [{ ...property, type: PropertyFilterType.Event } as EventPropertyFilter],
                },
            ],
        })

        expect(aligned.event.properties[property.key]).toEqual(expected)
    })

    it('removes copied survey response properties that do not have a target question', () => {
        const copiedInputs = {
            text: {
                value: "First: {event.properties['$survey_response_source-a']} extra: {event.properties['$survey_response_source-b']}",
            },
            body: {
                value: {
                    '$survey_response_source-a': "{event.properties['$survey_response_source-a']}",
                    '$survey_response_source-b': "{event.properties['$survey_response_source-b']}",
                },
            },
        }

        expect(
            remapSurveyResponseProperties(copiedInputs, {
                id: 'target-survey',
                name: 'Target survey',
                enable_partial_responses: true,
                questions: [{ id: 'target-a', question: 'First?', type: SurveyQuestionType.Open }],
            })
        ).toEqual({
            text: {
                value: "First: {event.properties['$survey_response_target-a']} extra: ",
            },
            body: {
                value: {
                    '$survey_response_target-a': "{event.properties['$survey_response_target-a']}",
                },
            },
        })
    })
})

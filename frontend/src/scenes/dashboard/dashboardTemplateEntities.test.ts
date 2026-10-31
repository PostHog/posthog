import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, EntityTypes, TemplateVariableStep } from '~/types'

import { seriesToTemplateVariableStep, templateVariableStepToSeries } from './dashboardTemplateEntities'

const currentUrlContainsPricing = { key: '$current_url', value: 'pricing', operator: 'icontains', type: 'event' }

describe('dashboardTemplateEntities', () => {
    test.each<[string, TemplateVariableStep, Record<string, unknown>]>([
        [
            'an event keeps its math, custom name and properties, and drops a stored event key',
            {
                id: '$pageview',
                event: '$pageview',
                math: BaseMathType.UniqueUsers,
                type: EntityTypes.EVENTS,
                order: 2,
                name: '$pageview',
                custom_name: 'Pricing page views',
                properties: [currentUrlContainsPricing],
            },
            {
                id: '$pageview',
                math: BaseMathType.UniqueUsers,
                type: EntityTypes.EVENTS,
                order: 0,
                name: '$pageview',
                custom_name: 'Pricing page views',
                properties: [currentUrlContainsPricing],
            },
        ],
        [
            'an event the project never captured keeps its custom event flag',
            { id: 'signed_up', custom_event: true, type: EntityTypes.EVENTS, name: 'signed_up' },
            { id: 'signed_up', custom_event: true, type: EntityTypes.EVENTS, name: 'signed_up', order: 0 },
        ],
        [
            'an action keeps its element selector and comes back with a numeric id',
            {
                id: '42',
                math: BaseMathType.UniqueUsers,
                name: 'Clicked sign up',
                custom_name: 'Sign ups',
                order: 0,
                type: EntityTypes.ACTIONS,
                selector: 'button.signup',
                href: '/signup',
                url: 'https://example.com',
            },
            {
                id: 42,
                math: BaseMathType.UniqueUsers,
                name: 'Clicked sign up',
                custom_name: 'Sign ups',
                order: 0,
                type: EntityTypes.ACTIONS,
                selector: 'button.signup',
                href: '/signup',
                url: 'https://example.com',
            },
        ],
        [
            'a group keeps its operator and nested event and action',
            {
                type: EntityTypes.GROUPS,
                name: 'Signed up or purchased',
                math: BaseMathType.UniqueUsers,
                operator: 'OR',
                order: 0,
                nestedFilters: [
                    { id: 'signed_up', type: EntityTypes.EVENTS, name: 'signed_up', order: 0 },
                    {
                        id: '12',
                        type: EntityTypes.ACTIONS,
                        name: 'Purchased',
                        order: 1,
                        properties: [currentUrlContainsPricing],
                    },
                ],
            } as TemplateVariableStep,
            {
                id: null,
                type: EntityTypes.GROUPS,
                name: 'Signed up or purchased',
                math: BaseMathType.UniqueUsers,
                operator: 'OR',
                order: 0,
                nestedFilters: [
                    { id: 'signed_up', type: EntityTypes.EVENTS, name: 'signed_up', order: 0 },
                    {
                        id: 12,
                        type: EntityTypes.ACTIONS,
                        name: 'Purchased',
                        order: 1,
                        properties: [currentUrlContainsPricing],
                    },
                ],
            },
        ],
    ])('%s', (_, stored, expected) => {
        expect(seriesToTemplateVariableStep(templateVariableStepToSeries(stored))).toEqual(expected)
    })

    test.each<[string, SeriesNode[], Record<string, unknown> | undefined]>([
        ['no rows store no step', [], undefined],
        [
            'a row the picker built drops its node version and keeps its math',
            [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: 'total',
                    version: 1,
                } as SeriesNode,
            ],
            { id: '$pageview', type: EntityTypes.EVENTS, name: '$pageview', math: 'total', order: 0 },
        ],
        [
            'an action row wins over an earlier event row and keeps its own index',
            [
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
                { kind: NodeKind.ActionsNode, id: 7, name: 'Purchased' },
            ],
            { id: 7, type: EntityTypes.ACTIONS, name: 'Purchased', order: 1 },
        ],
    ])('%s', (_, series, expected) => {
        expect(seriesToTemplateVariableStep(series)).toEqual(expected)
    })
})

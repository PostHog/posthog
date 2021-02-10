import React from 'react'
import { Insights } from './Insights'
import * as helpers from 'cypress/support/helpers'

describe('<Insights /> trends', () => {
    const mount = () => helpers.mountPage(<Insights />)
    const baseLocation = () => {
        helpers.setLocation('/insights', {
            insight: 'TRENDS',
            interval: 'day',
            display: 'ActionsLineGraph',
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                },
            ],
            properties: [],
        })
    }

    beforeEach(() => {
        cy.intercept('/api/user/', { fixture: 'api/user' })
        cy.intercept('/api/dashboard/', { fixture: 'api/dashboard' })
        cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/annotation/', { fixture: 'api/annotations' })
        cy.intercept('/api/action/', { fixture: 'api/action/actions' })
        cy.intercept('/api/cohort/', { fixture: 'api/cohort/cohorts' })
        cy.intercept('/api/insight/', { fixture: 'api/insight/trends' }).as('api_insight')
        cy.intercept('/api/person/properties/', { fixture: 'api/person/properties' })

        helpers.mockPosthog()
    })

    it('loads default trends', () => {
        baseLocation()
        mount()
        cy.wait('@api_insight')
            .map(helpers.getSearchParameters)
            .should('include', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: JSON.stringify([
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ]),
                properties: '[]',
            })

        cy.get('[data-attr="trend-line-graph"]').should('be.visible')
    })

    it('clicks on active user filter', () => {
        baseLocation()
        mount()
        cy.wait('@api_insight')
            .map(helpers.getSearchParameters)
            .should('include', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: JSON.stringify([
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ]),
                properties: '[]',
            })

        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-dau-0]').click()

        cy.wait('@api_insight')
        cy.get('@api_insight')
            .map(helpers.getSearchParameters)
            .should('include', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: JSON.stringify([
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                        math: 'dau',
                    },
                ]),
                properties: '[]',
            })
        cy.get('[data-attr="trend-line-graph"]').should('be.visible')
    })

    it('adds another entity filter', () => {
        baseLocation()
        mount()
        cy.wait('@api_insight')
            .map(helpers.getSearchParameters)
            .should('include', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: JSON.stringify([
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ]),
                properties: '[]',
            })
        // when
        cy.contains('Add graph series').click()
        cy.wait('@api_insight')
            .map(helpers.getSearchParameters)
            .should('include', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: JSON.stringify([
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 1,
                    },
                ]),
                properties: '[]',
            })
        cy.get('[data-attr=trend-element-subject-1]').click()
        // then
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    describe('Trend filters from url', () => {
        it('renders multiple entities', () => {
            helpers.setLocation('/insights', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ],
                actions: [
                    {
                        id: 8,
                        name: 'Entered Free Trial',
                        type: 'actions',
                        order: 1,
                    },
                ],
                properties: [],
            })
            mount()

            cy.wait('@api_insight')
                .map(helpers.getSearchParameters)
                .should('include', {
                    insight: 'TRENDS',
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    events: JSON.stringify([
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ]),
                    actions: JSON.stringify([
                        {
                            id: 8,
                            name: 'Entered Free Trial',
                            type: 'actions',
                            order: 1,
                        },
                    ]),
                    properties: '[]',
                })
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
        })

        it('renders single prop', () => {
            helpers.setLocation('/insights', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ],
                properties: [
                    {
                        key: '$browser',
                        value: 'Chrome',
                        operator: 'exact',
                        type: 'event',
                    },
                ],
            })
            mount()

            cy.wait('@api_insight')
                .map(helpers.getSearchParameters)
                .should('include', {
                    insight: 'TRENDS',
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    events: JSON.stringify([
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ]),
                    properties: JSON.stringify([
                        {
                            key: '$browser',
                            value: 'Chrome',
                            operator: 'exact',
                            type: 'event',
                        },
                    ]),
                })

            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('Chrome').should('be.visible')
        })

        it('renders multiple prop', () => {
            helpers.setLocation('/insights', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ],
                properties: [
                    {
                        key: '$browser',
                        value: 'Chrome',
                        operator: 'exact',
                        type: 'event',
                    },
                    {
                        key: '$current_url',
                        value: 'http://posthog.com',
                        operator: 'exact',
                        type: 'event',
                    },
                ],
            })
            mount()

            cy.wait('@api_insight')
                .map(helpers.getSearchParameters)
                .should('include', {
                    insight: 'TRENDS',
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    events: JSON.stringify([
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ]),
                    properties: JSON.stringify([
                        {
                            key: '$browser',
                            value: 'Chrome',
                            operator: 'exact',
                            type: 'event',
                        },
                        {
                            key: '$current_url',
                            value: 'http://posthog.com',
                            operator: 'exact',
                            type: 'event',
                        },
                    ]),
                })

            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('http://posthog.com').should('be.visible')
        })

        it('responsive to shown as', () => {
            helpers.setLocation('/insights', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ],
                properties: [],
                shown_as: 'Stickiness',
            })
            mount()
            cy.wait('@api_insight')
                .map(helpers.getSearchParameters)
                .should('include', {
                    insight: 'TRENDS',
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    events: JSON.stringify([
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ]),
                    properties: '[]',
                    shown_as: 'Stickiness',
                })
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('Stickiness').should('be.visible')
        })

        it('responsive to breakdown', () => {
            helpers.setLocation('/insights', {
                insight: 'TRENDS',
                interval: 'day',
                display: 'ActionsLineGraph',
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                    },
                ],
                properties: [],
                breakdown: '$browser',
                breakdown_type: 'event',
            })
            mount()

            cy.wait('@api_insight')
                .map(helpers.getSearchParameters)
                .should('include', {
                    insight: 'TRENDS',
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    events: JSON.stringify([
                        {
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                            order: 0,
                        },
                    ]),
                    properties: '[]',
                    breakdown: '$browser',
                    breakdown_type: 'event',
                })
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('$browser').should('be.visible')
        })
    })
})

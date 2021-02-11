import React from 'react'
import { Insights } from './Insights'
import * as helpers from 'cypress/support/helpers'
import { toParams } from 'lib/utils'

describe('<Insights /> trends', () => {
    const mount = () => helpers.mountPage(<Insights />)

    const mountAndCheckAPI = () => {
        helpers.setLocation('/insights', given.params)
        mount()

        cy.wait('@api_insight').its('request.url').should('contain', toParams(given.params))
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

    given('params', () => ({
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
    }))

    it('loads default trends', () => {
        mountAndCheckAPI()
        cy.wait('@api_insight')
            .map(helpers.getSearchParameters)
            .should('eq', {
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

    it('responds to active user filter', () => {
        mountAndCheckAPI()

        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-dau-0]').click()

        cy.wait('@api_insight')
        cy.get('@api_insight')
            .map(helpers.getSearchParameters)
            .should('include', {
                events: JSON.stringify([
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        order: 0,
                        math: 'dau',
                    },
                ]),
            })
        cy.get('[data-attr="trend-line-graph"]').should('be.visible')
    })

    describe('filtered in url', () => {
        it('responds to multiple entities', () => {
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
                })
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
        })

        it('responds to a single prop', () => {
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

        it('responds to multiple props', () => {
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

        it('reponds to shown as parameter', () => {
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
            cy.wait('@api_insight').map(helpers.getSearchParameters).should('include', {
                shown_as: 'Stickiness',
            })
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('Stickiness').should('be.visible')
        })

        it('responds to breakdown paramters', () => {
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

            cy.wait('@api_insight').map(helpers.getSearchParameters).should('include', {
                breakdown: '$browser',
                breakdown_type: 'event',
            })
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('$browser').should('be.visible')
        })
    })
})

import React from 'react'
import { Insights } from './Insights'
import * as helpers from 'cypress/support/helpers'
import { toParams } from 'lib/utils'

// These tests are broken in our CI pipeline and not sure how to fix them
// Could still be useful locally

xdescribe('<Insights /> trends', () => {
    const mount = () => helpers.mountPage(<Insights />)

    const mountAndCheckAPI = () => {
        helpers.setLocation('/insights', given.params)
        mount()

        cy.wait('@api_insight').its('request.url').should('contain', toParams(given.params))
    }

    beforeEach(() => {
        cy.intercept('/_preflight/', { fixture: '_preflight' })
        cy.intercept('/api/users/@me/', { fixture: 'api/users/@me' })
        cy.intercept('/api/projects/2/dashboards/', { fixture: 'api/dashboard' })
        cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/annotation/', { fixture: 'api/annotations' })
        cy.intercept('/api/action/', { fixture: 'api/action/actions' })
        cy.intercept('/api/cohort/', { fixture: 'api/cohort/cohorts' })
        cy.intercept('/api/person/properties/', { fixture: 'api/person/properties' })
        cy.interceptLazy('/api/projects/2/insights/', () => ({ fixture: 'api/insight/trends' })).as('api_insight')

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
    }))

    it('loads default trends', () => {
        mountAndCheckAPI()

        cy.get('.insights-page').should('be.visible')
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

    it('can render bar graphs', () => {
        mountAndCheckAPI()

        cy.overrideInterceptLazy('/api/projects/2/insights/', () => ({ fixture: 'api/insight/trends/breakdown' }))

        cy.get('[data-attr=add-breakdown-button]').click()
        cy.get('[data-attr=prop-breakdown-select]').click().type('Browser').type('{enter}')

        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Value').click()
        cy.get('body').click()

        cy.wait(1000)
        cy.get('.graph-container').should('be.visible')

        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Time').click()
        cy.get('body').click()

        cy.wait(1000)
        cy.get('.graph-container').should('be.visible')
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
            cy.get('[data-attr="property-filter-0"]').should('contain', 'Chrome')
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
            cy.get('[data-attr="property-filter-0"]').should('contain', 'Chrome')
            cy.get('[data-attr="property-filter-1"]').should('contain', 'http://posthog.com')
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
            cy.get('[data-attr="add-breakdown-button"]').should('contain', 'Browser')
        })
    })
})

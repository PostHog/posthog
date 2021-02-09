import React from 'react'
import { Insights } from './Insights'
import * as helpers from 'cypress/support/helpers'

describe('<Insights /> trends', () => {
    const mount = () => helpers.mountPage(<Insights />)

    beforeEach(() => {
        cy.intercept('/api/user/', { fixture: 'api/user' })
        cy.intercept('/api/dashboard/', { fixture: 'api/dashboard' })
        cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/annotation/', { fixture: 'api/annotations' })
        cy.intercept('/api/action/', { fixture: 'api/action/actions' })
        cy.intercept('/api/cohort/', { fixture: 'api/cohort/cohorts' })
        cy.intercept('/api/insight/', { fixture: 'api/insight/trends' })
        cy.intercept('/api/person/properties/', { fixture: 'api/person/properties' })

        helpers.mockPosthog()
    })

    it('Basic load', () => {
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
        mount()
        cy.get('[data-attr="trend-line-graph"]').should('be.visible')
    })

    describe('Trend filters from url', () => {
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
            cy.get('[data-attr="trend-line-graph"]').should('be.visible')
            cy.contains('http://posthog.com').should('be.visible')
        })
    })
})

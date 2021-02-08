import React from 'react'
import { Sessions } from './Sessions'
import * as helpers from 'cypress/support/helpers'

describe('<Sessions />', () => {
    beforeEach(() => {
        cy.intercept('/api/user/', { fixture: 'api/user' })
        cy.intercept('/api/dashboard/', { fixture: 'api/dashboard' })
        cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/person/properties/', { fixture: 'api/person/properties' })
        cy.interceptLazy('/api/event/sessions/', () => given.sessions).as('api_sessions')

        helpers.mockPosthog()
        helpers.setLocation('/sessions')
    })

    given('sessions', () => ({ fixture: 'api/event/sessions/demo_sessions' }))

    it('can navigate within sessions page', () => {
        helpers.mountPage(<Sessions />, { cssFile: 'sessions.css' })

        cy.contains('Sessions').should('be.visible')
        cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
            date_from: '2021-01-05',
            date_to: '2021-01-05',
            distinct_id: '',
            filters: '[]',
            offset: '0',
            properties: '[]',
        })

        cy.log('Play all disabled')
        cy.get('[data-attr="play-all-recordings"]').should('have.attr', 'disabled')

        cy.log('Load more should work')
        cy.get('[data-attr="load-more-sessions"]').click()
        cy.wait('@api_sessions')
            .map(helpers.getSearchParameters)
            .should('include', {
                date_from: '2021-01-05',
                date_to: '2021-01-05',
                pagination: JSON.stringify({ offset: 10 }),
            })
    })

    describe('sessions filters', () => {
        given('featureFlags', () => ['filter_by_session_props'])

        beforeEach(() => {
            cy.intercept('/api/sessions_filter/', { fixture: 'api/sessions_filter' }).as('sessions_filter')
        })

        it('renders sessions filters', () => {
            helpers.mountPage(<Sessions />, { cssFile: 'sessions.css' })

            cy.wait('@sessions_filter')
            cy.contains('Unseen recordings').should('be.visible')
            cy.contains('ChromeUsers').should('be.visible')

            cy.get('[data-attr="sessions-filter-link"]').last().click()
            cy.wait('@api_sessions')

            cy.get('@api_sessions').map(helpers.getSearchParameters).should('include', {
                filters: '[{"key":"$browser","type":"person","label":"$browser","value":"Chrome","operator":"exact"}]',
            })

            cy.pause()
        })
    })
})

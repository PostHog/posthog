import React from 'react'
import { Sessions } from './Sessions'
import * as helpers from 'cypress/support/helpers'

describe('<Sessions />', () => {
    const mount = () => helpers.mountPage(<Sessions />, { cssFile: 'sessions.css' })

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

    given('featureFlags', () => ['filter_by_session_props'])
    given('sessions', () => ({ fixture: 'api/event/sessions/demo_sessions' }))

    it('can navigate within sessions page', () => {
        mount()

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

        cy.get('[data-attr="sessions-prev-date"]').click()
        cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
            date_from: '2021-01-04',
            date_to: '2021-01-04',
        })
    })

    it('can filter sessions', () => {
        mount()
        cy.wait('@api_sessions')

        cy.get('[data-attr="sessions-filter-open"]').click()
        cy.focused().type('br').type('{downarrow}').type('{enter}')
        cy.get('.sessions-filter-row input').last().type('Chrome').type('{enter}')

        cy.contains('There are unapplied filters').should('be.visible')
        cy.get('[data-attr="sessions-apply-filters"]').click()
        cy.contains('There are unapplied filters').should('not.exist')

        cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
            filters: '[{"type":"person","key":"$browser","value":"Chrome","label":"$browser","operator":"exact"}]',
        })
    })

    describe('sessions filters', () => {
        beforeEach(() => {
            cy.intercept('/api/sessions_filter/', { fixture: 'api/sessions_filter' }).as('sessions_filter')
        })

        it('renders sessions filters', () => {
            mount()

            cy.wait('@sessions_filter')
            cy.contains('Unseen recordings').should('be.visible')
            cy.contains('ChromeUsers').should('be.visible')

            cy.get('[data-attr="sessions-filter-link"]').last().click()

            cy.wait('@api_sessions')
            cy.get('@api_sessions').map(helpers.getSearchParameters).should('include', {
                filters: '[{"key":"$browser","type":"person","label":"$browser","value":"Chrome","operator":"exact"}]',
            })
        })
    })
})

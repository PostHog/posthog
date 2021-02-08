import React from 'react'
import { Sessions } from '~/scenes/sessions/Sessions'
import { mountPage, setLocation, getSearchParameters } from 'cypress/support/helpers'

describe('<Sessions />', () => {
    beforeEach(() => {
        cy.intercept('/api/user/', { fixture: 'api/user' })
        cy.intercept('/api/dashboard/', { fixture: 'api/dashboard' })
        cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/person/properties/', { fixture: 'api/person/properties' })
        cy.interceptLazy('/api/sessions_filter/', () => given.sessionsFilter).as('api_sessions_filter')
        cy.intercept('/api/event/sessions', { fixture: 'api/event/sessions/demo_sessions' }).as('api_sessions')
    })

    given('sessionsFilter', () => ({ results: [] }))

    it('loads sessions data', () => {
        setLocation('/sessions')
        mountPage(<Sessions />, { featureFlags: ['filter_by_session_props'], cssFile: 'sessions.css' })

        cy.contains('Sessions').should('be.visible')
        cy.wait('@api_sessions').map(getSearchParameters).should('include', {
            date_from: '2021-01-05',
            date_to: '2021-01-05',
            distinct_id: '',
            filters: '[]',
            offset: '0',
            properties: '[]',
        })

        cy.get('[data-attr="load-more-sessions"]').click()
        cy.wait('@api_sessions')
            .map(getSearchParameters)
            .should('include', {
                date_from: '2021-01-05',
                date_to: '2021-01-05',
                pagination: JSON.stringify({ offset: 10 }),
            })

        // Navigate back/forward in time.
        // Session recording disabled
        // Toggle feature flags on-off
    })
})

// const readFixture = (name) => {
//     import fs from 'fs'

//     const filepath =
//     return JSON.parse(fs.readFileSync())
// }

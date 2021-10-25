import React from 'react'
import { Person } from './Person'
import * as helpers from 'cypress/support/helpers'

describe('<Person /> ', () => {
    const mount = () => helpers.mountPage(<Person />)

    beforeEach(() => {
        cy.intercept('/_preflight/', { fixture: '_preflight' })
        cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
        cy.intercept('/api/users/@me/', { fixture: 'api/users/@me' })
        cy.intercept('/api/person/', { fixture: 'api/person' }).as('api_person')
        cy.intercept('/api/projects/2/events/?', { fixture: 'api/event/single_person_events' }).as('api_event')

        helpers.mockPosthog()
        helpers.setLocation('/person/01779064-53be-000c-683f-23b1a8c8eb4c')
    })

    it('shows user properties and events', () => {
        mount()

        cy.wait('@api_person').map(helpers.getSearchParameters).should('eql', {
            distinct_id: '01779064-53be-000c-683f-23b1a8c8eb4c',
        })

        cy.get('[data-test-person-details]').contains('smith.nunez@gmail.com').should('be.visible')

        cy.wait('@api_event').map(helpers.getSearchParameters).should('eql', {
            orderBy: '["-timestamp"]',
            person_id: '1',
            properties: '[]',
        })

        cy.get('.event-row').should('have.length', 7)
    })

    describe('sessions tab', () => {
        beforeEach(() => {
            cy.intercept('/api/projects/2/dashboards/', { fixture: 'api/dashboard' })
            cy.intercept('/api/personal_api_keys/', { fixture: 'api/personal_api_keys' })
            cy.intercept('/api/projects/@current/', { fixture: 'api/projects/@current' })
            cy.intercept('/api/projects/2/events/sessions/', {
                fixture: 'api/event/sessions/session_with_recording',
            }).as('api_sessions')
            cy.intercept('/api/projects/2/events/session_recording', { fixture: 'api/event/session_recording' }).as(
                'api_session_recording'
            )
        })

        it('sees sessions and session recordings', () => {
            mount()
            cy.wait('@api_person')

            cy.get('[data-attr="person-sessions-tab"]').click()

            cy.wait('@api_sessions').map(helpers.getSearchParameters).should('include', {
                date_from: '2020-01-05',
                date_to: '2020-01-05',
                distinct_id: '01779064-53be-000c-683f-23b1a8c8eb4c',
            })

            cy.get('[data-attr="sessions-date-picker"]').should('have.value', '2020-01-05')

            cy.get('[data-attr="session-recordings-button"]').click()
            cy.wait('@api_session_recording').map(helpers.getSearchParameters).should('eql', {
                session_recording_id: '177902024d94f6-022e8a39d6abb8-3b710f51-1fa400-177902024da550',
                save_view: 'true',
            })

            cy.contains('19 second session on Jan 29th').should('be.visible')
            cy.contains('1276 x 1300').should('be.visible')
        })
    })
})

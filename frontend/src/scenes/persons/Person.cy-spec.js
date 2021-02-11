import React from 'react'
import { Person } from './Person'
import * as helpers from 'cypress/support/helpers'

describe('<Person /> ', () => {
    const mount = () => helpers.mountPage(<Person />)

    beforeEach(() => {
        cy.intercept('/api/user/', { fixture: 'api/user' })
        cy.intercept('/api/person/', { fixture: 'api/person' }).as('api_person')
        cy.intercept('/api/event/', { fixture: 'api/event/single_person_events' }).as('api_event')

        helpers.mockPosthog()
        helpers.setLocation('/person/01779064-53be-000c-683f-23b1a8c8eb4c')
    })

    given('featureFlags', () => ['persons-2353'])

    it('shows user properties and events', () => {
        mount()

        cy.wait('@api_person').map(helpers.getSearchParameters).should('eql', {
            distinct_id: '01779064-53be-000c-683f-23b1a8c8eb4c',
        })

        cy.get('[data-test-person-details]').contains('smith.nunez@gmail.com').should('be.visible')

        cy.wait('@api_event').map(helpers.getSearchParameters).should('eql', {
            orderBy: '["-timestamp"]',
            person_id: '1',
            properties: '{}',
        })

        cy.get('.event-row').should('have.length', 7)
    })
})

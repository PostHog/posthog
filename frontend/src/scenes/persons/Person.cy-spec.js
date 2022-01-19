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

    it('shows user properties', () => {
        mount()

        cy.wait('@api_person').map(helpers.getSearchParameters).should('eql', {
            distinct_id: '01779064-53be-000c-683f-23b1a8c8eb4c',
        })

        cy.get('.page-title').contains('smith.nunez@gmail.com').should('be.visible')
    })
})

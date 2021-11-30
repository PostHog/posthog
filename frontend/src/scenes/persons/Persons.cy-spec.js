import React from 'react'
import { Persons } from './Persons'
import * as helpers from 'cypress/support/helpers'

describe('<Person /> ', () => {
    const mount = () => helpers.mountPage(<Persons />)

    beforeEach(() => {
        cy.intercept('/_preflight/', { fixture: '_preflight' })
        cy.intercept('/api/users/@me/', { fixture: 'api/users/@me' })
        cy.intercept('/api/person/', { fixture: 'api/person/persons' }).as('api_persons')

        helpers.mockPosthog()
        helpers.setLocation('/persons')
    })

    it('person search', () => {
        mount()

        cy.wait('@api_persons').map(helpers.getSearchParameters).should('be.empty')
        cy.get('[data-attr="persons-search"]').type('01776f08-b02e-0025-98c6-d8c376e3617b', { delay: 1 })
        cy.get('[data-attr="persons-search"]').type('{enter}')

        cy.wait('@api_persons').map(helpers.getSearchParameters).should('include', {
            search: '01776f08-b02e-0025-98c6-d8c376e3617b',
        })
    })

    it('person row click', () => {
        mount()

        cy.wait('@api_persons').map(helpers.getSearchParameters).should('be.empty')
        cy.get('[data-attr="goto-person-email-01776f08-b02e-0025-98c6-d8c376e3617b"]').click()
        cy.wait('@api_persons').map(helpers.getSearchParameters).should('include', {
            distinct_id: '01776f08-b02e-0025-98c6-d8c376e3617b',
        })
    })
})

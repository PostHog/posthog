import React from 'react'
import { Persons } from './Persons'
import * as helpers from 'cypress/support/helpers'

describe('<Person /> ', () => {
    const mount = () => helpers.mountPage(<Persons />)

    beforeEach(() => {
        cy.intercept('/api/user/', { fixture: 'api/user' })
        cy.intercept('/api/person/', { fixture: 'api/person/persons' }).as('api_persons')

        helpers.mockPosthog()
        helpers.setLocation('/persons')
    })

    given('featureFlags', () => ['persons-2353'])

    it('person type tabs', () => {
        mount()
        cy.contains('Persons').should('be.visible')
        cy.wait('@api_persons').map(helpers.getSearchParameters).should('be.empty')
        cy.get('[data-attr="people-types-tab-identified"]').click({ force: true })
        cy.wait('@api_persons').map(helpers.getSearchParameters).should('include', {
            is_identified: 'true',
        })

        cy.get('[data-attr="people-types-tab-anonymous"]').click({ force: true })
        cy.wait('@api_persons').map(helpers.getSearchParameters).should('include', {
            is_identified: 'false',
        })
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
        cy.get('[data-attr="goto-person-arrow-0"]').click()
        cy.wait('@api_persons').map(helpers.getSearchParameters).should('include', {
            distinct_id: '01776f08-b02e-0025-98c6-d8c376e3617b',
        })
    })
})

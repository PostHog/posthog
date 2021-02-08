import React from 'react'
import { Persons } from './Persons'
import * as helpers from 'cypress/support/helpers'

describe('<Person /> ', () => {
    const mount = () => helpers.mountPage(<Persons />, { cssFile: 'persons.css' })

    beforeEach(() => {
        cy.interceptLazy('/api/person/', () => given.persons).as('api_persons')

        helpers.mockPosthog()
        helpers.setLocation('/persons')
    })

    given('featureFlags', () => ['persons-2353'])
    given('persons', () => ({ fixture: 'api/person/persons' }))

    it('can navigate within person page', () => {
        mount()
        cy.contains('Persons').should('be.visible')
    })
})

import '@cypress/react/support'
import 'givens/setup'
import './commands'

import { unmount } from '@cypress/react'

try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    require('cypress-terminal-report/src/installLogsCollector')()
} catch {}

beforeEach(() => {
    if (Cypress.spec.specType === 'component') {
        // Freeze time to 2021.01.05 Noon UTC - this should be the same date regardless of timezone.
        cy.clock(1578225600000, ['Date'])
    } else {
        cy.visit('/')

        cy.url().then((url) => {
            if (url.includes('login')) {
                logIn()
            }
        })
    }
})

afterEach(() => {
    if (Cypress.spec.specType === 'component') {
        unmount()
    }
})

const logIn = () => {
    cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com')

    cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

    cy.get('[type=submit]').click()
}

Cypress.on('uncaught:exception', () => {
    return false
})

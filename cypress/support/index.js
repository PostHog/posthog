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
        if (Cypress.spec.name.includes('Premium')) {
            cy.visit('/login')
            cy.intercept('/api/users/@me/', { fixture: 'api/user-enterprise' })
            cy.login()
        } else {
            cy.visit('/')

            cy.url().then((url) => {
                if (url.includes('login')) {
                    cy.login()
                }
            })
        }
    }
})

afterEach(() => {
    if (Cypress.spec.specType === 'component') {
        unmount()
    }
})

Cypress.on('uncaught:exception', () => {
    return false
})

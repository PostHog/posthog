import '@cypress/react/support'
import 'givens/setup'
import './commands'

import { unmount } from '@cypress/react'

try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    require('cypress-terminal-report/src/installLogsCollector')()
} catch {}

// Add console errors into cypress logs. This helps with failures in Github Actions which otherwise swallows them.
// From: https://github.com/cypress-io/cypress/issues/300#issuecomment-688915086
Cypress.on('window:before:load', (win) => {
    cy.spy(win.console, 'error')
    cy.spy(win.console, 'warn')
})

beforeEach(() => {
    if (Cypress.spec.specType === 'component') {
        // Freeze time to 2021.01.05 Noon UTC - this should be the same date regardless of timezone.
        cy.clock(1578225600000, ['Date'])
    } else {
        if (Cypress.spec.name.includes('Premium')) {
            cy.visit('/login?next=/?no-preloaded-app-context=true')
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

beforeEach(() => {
    if (Cypress.spec.specType !== 'component') {
        // Make sure the insights page is actually loaded before running tests
        cy.get('.insights-page').should('exist')
    }
})

afterEach(() => {
    if (Cypress.spec.specType === 'component') {
        unmount()
    }
})

const resizeObserverLoopErrRe = /^[^(ResizeObserver loop limit exceeded)]/
Cypress.on('uncaught:exception', (err) => {
    /* returning false here prevents Cypress from failing the test */
    if (resizeObserverLoopErrRe.test(err.message)) {
        return false
    }
})

import 'givens/setup'
import './commands'

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
    if (Cypress.spec.name.includes('Premium')) {
        cy.intercept('/api/users/@me/', { fixture: 'api/user-enterprise' })

        cy.request('POST', '/api/login/', {
            email: 'test@posthog.com',
            password: '12345678',
        })
        cy.visit('/?no-preloaded-app-context=true')
    } else {
        cy.request('POST', '/api/login/', {
            email: 'test@posthog.com',
            password: '12345678',
        })
        cy.visit('/insights')
        cy.get('.saved-insights').should('exist')
    }
})

const resizeObserverLoopErrRe = /^[^(ResizeObserver loop limit exceeded)]/
Cypress.on('uncaught:exception', (err) => {
    /* returning false here prevents Cypress from failing the test */
    if (resizeObserverLoopErrRe.test(err.message)) {
        return false
    }
})

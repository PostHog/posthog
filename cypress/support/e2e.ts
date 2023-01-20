import 'givens/setup'
import './commands'
import 'cypress-axe'
import { decideResponse } from '../fixtures/api/decide'

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
    cy.intercept('api/prompts/my_prompts/', { sequences: [], state: {} })

    cy.intercept('https://app.posthog.com/decide/*', (req) =>
        req.reply(
            decideResponse({
                // set feature flags here e.g.
                // 'toolbar-launch-side-action': true,
            })
        )
    )

    if (Cypress.spec.name.includes('Premium')) {
        cy.intercept('/api/users/@me/', { fixture: 'api/user-enterprise' })

        cy.request('POST', '/api/login/', {
            email: 'test@posthog.com',
            password: '12345678',
        })
        cy.visit('/?no-preloaded-app-context=true')
    } else {
        cy.intercept('GET', /\/api\/projects\/\d+\/insights\/?\?/).as('getInsights')

        cy.request('POST', '/api/login/', {
            email: 'test@posthog.com',
            password: '12345678',
        })
        cy.visit('/insights')
        cy.wait('@getInsights').then(() => {
            cy.get('.saved-insights tr').should('exist')
        })
    }
})

const resizeObserverLoopErrRe = /^[^(ResizeObserver loop limit exceeded)]/
Cypress.on('uncaught:exception', (err) => {
    /* returning false here prevents Cypress from failing the test */
    if (resizeObserverLoopErrRe.test(err.message)) {
        return false
    }
})

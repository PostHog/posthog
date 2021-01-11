import './commands'

// eslint-disable-next-line @typescript-eslint/no-var-requires
require('cypress-terminal-report/src/installLogsCollector')()

beforeEach(() => {
    cy.visit('/')

    cy.url().then((url) => {
        if (url.includes('login')) {
            logIn()
        }
    })
})

const logIn = () => {
    cy.get('#inputEmail').type('test@posthog.com').should('have.value', 'test@posthog.com')

    cy.get('#inputPassword').type('pass').should('have.value', 'pass')

    cy.get('.btn').click()
}

Cypress.on('uncaught:exception', () => {
    return false
})

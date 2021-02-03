import '@cypress/react/support'
import 'given2/setup'
import './commands'

try{
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    require('cypress-terminal-report/src/installLogsCollector')()
} catch {}

beforeEach(() => {
    if (Cypress.spec.specType === 'component') {
        // Freeze time to 2021.01.05
        cy.clock(1609804800000, ['Date'])
    } else {
        cy.visit('/')

        cy.url().then((url) => {
            if (url.includes('login')) {
                logIn()
            }
        })
    }
})

const logIn = () => {
    cy.get('#inputEmail').type('test@posthog.com').should('have.value', 'test@posthog.com')

    cy.get('#inputPassword').type('12345678').should('have.value', '12345678')

    cy.get('.btn').click()
}

Cypress.on('uncaught:exception', () => {
    return false
})

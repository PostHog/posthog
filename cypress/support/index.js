import './commands'

beforeEach(() => {
    cy.visit('/')

    cy.url().then(url => {
        if (url.includes('setup_admin')) {
            cy.get('#inputCompany')
                .type('company')
                .should('have.value', 'company')

            cy.get('#inputName')
                .type('name')
                .should('have.value', 'name')

            cy.get('#inputEmail')
                .type('fake@posthog.com')
                .should('have.value', 'fake@posthog.com')

            cy.get('#inputPassword')
                .type('password')
                .should('have.value', 'password')

            cy.get('.btn').click()

            cy.visit('/demo')
            cy.visit('/')
        } else if (url.includes('login')) {
            cy.get('#inputEmail')
                .type('fake@posthog.com')
                .should('have.value', 'fake@posthog.com')

            cy.get('#inputPassword')
                .type('password')
                .should('have.value', 'password')

            cy.get('.btn').click()
        }
    })
})

Cypress.on('uncaught:exception', () => {
    return false
})

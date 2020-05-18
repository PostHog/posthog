import './commands'

beforeEach(() => {
    cy.visit('http://localhost:8000')

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
    cy.visit('http://localhost:8000/demo')
    cy.visit('http://localhost:8000')
})

Cypress.on('uncaught:exception', err => {
    return false
})

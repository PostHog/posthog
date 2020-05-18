// ***********************************************************
// This example support/index.js is processed and
// loaded automatically before your test files.
//
// This is a great place to put global configuration and
// behavior that modifies Cypress.
//
// You can change the location of this file or turn off
// automatically serving support files with the
// 'supportFile' configuration option.
//
// You can read more here:
// https://on.cypress.io/configuration
// ***********************************************************

// Import commands.js using ES2015 syntax:
import './commands'

// Alternatively you can use CommonJS syntax:
// require('./commands')

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
                .type('fake@email.com')
                .should('have.value', 'fake@email.com')

            cy.get('#inputPassword')
                .type('password')
                .should('have.value', 'password')

            cy.get('.btn').click()
        } else if (url.includes('login')) {
            cy.get('#inputEmail')
                .type('fake@email.com')
                .should('have.value', 'fake@email.com')

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

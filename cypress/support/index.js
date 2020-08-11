import './commands'

// eslint-disable-next-line @typescript-eslint/no-var-requires
require('cypress-terminal-report/src/installLogsCollector')()

beforeEach(() => {
    cy.visit('/')

    cy.url().then((url) => {
        if (url.includes('setup_admin')) {
            cy.get('#inputCompany').type('company').should('have.value', 'company')

            cy.get('#inputName').type('name').should('have.value', 'name')

            cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

            cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

            cy.get('.btn').click()

            cy.visit('/demo')
            cy.visit('/')
        } else if (url.includes('login')) {
            cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

            cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

            cy.get('.btn').click()
        }
        cy.wait(2000)
        cy.get('body').then(($body) => {
            if ($body.find('[data-attr=select-platform-Web]').length) {
                cy.get('[data-attr=select-platform-Web]').click()
                cy.get('[data-attr=wizard-step-counter]').should('contain', 'Step 2')
                cy.get('[data-attr=wizard-continue-button]').click()
                cy.get('[data-attr=wizard-complete-button]').should('exist')
                cy.get('[data-attr=wizard-complete-button]').click()
            }
        })
    })
})

Cypress.on('uncaught:exception', () => {
    return false
})

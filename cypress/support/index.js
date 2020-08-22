import './commands'

// eslint-disable-next-line @typescript-eslint/no-var-requires
require('cypress-terminal-report/src/installLogsCollector')()

beforeEach(() => {
    cy.visit('/')

    cy.url().then((url) => {
        if (url.includes('preflight')) {
            cy.get('.text-center > .ant-btn-default').click()
            cy.get('[style="margin-bottom: 64px;"] > .ant-btn').click()
            cy.wait(200)
            setupAdmin()
        } else if (url.includes('setup_admin')) {
            setupAdmin()
        } else if (url.includes('login')) {
            cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

            cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

            cy.get('.btn').click()
        }
        cy.get('body', { timeout: 7000 }).then(($body) => {
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

const setupAdmin = () => {
    cy.get('#inputCompany', { timeout: 7000 }).type('company').should('have.value', 'company')

    cy.get('#inputName').type('name').should('have.value', 'name')

    cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

    cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

    cy.get('.btn').click()

    cy.visit('/demo')
    cy.visit('/')
}

Cypress.on('uncaught:exception', () => {
    return false
})

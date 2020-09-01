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
            signUp()
        } else if (url.includes('signup')) {
            signUp()
        } else if (url.includes('login')) {
            cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

            cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

            cy.get('.btn').click()
        }
        cy.wait(200)
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

const signUp = () => {
    cy.get('#signupCompanyName', { timeout: 7000 }).type('Hedgehogs, Inc.').should('have.value', 'Hedgehogs, Inc.')

    cy.get('#signupFirstName').type('name').should('have.value', 'name')

    cy.get('#signupEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

    cy.get('#signupPassword').type('Test1234').should('have.value', 'Test1234')

    cy.get('button[data-attr="signup"]').click()

    cy.visit('/demo')
    cy.visit('/')
}

Cypress.on('uncaught:exception', () => {
    return false
})

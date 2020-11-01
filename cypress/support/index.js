import './commands'

// eslint-disable-next-line @typescript-eslint/no-var-requires
require('cypress-terminal-report/src/installLogsCollector')()

beforeEach(() => {
    cy.visit('/')

    const signupDetails = {
        name: 'name',
        company: 'Hedgehogs, Inc.',
        email: 'fake@posthog.com',
        password: 'Test1234',
    }

    cy.url().then((url) => {
        if (url.includes('preflight')) {
            cy.findByRole('button', { name: /Just experimenting/i }).click()
            cy.findByRole('button', { name: /Continue/i }).click()
            cy.signUp(signupDetails, true)
        } else if (url.includes('signup')) {
            cy.signUp(signupDetails, true)
        } else if (url.includes('login')) {
            cy.loginByForm()
        }

        cy.get('body').then(($body) => {
            if ($body.find('[data-attr=select-platform-Web]').length) {
                cy.findByRole('button', { name: /Web/i }).click()
                cy.findByTestId('wizard-step-counter').should('contain', 'Step 2')
                cy.findByRole('button', { name: /Continue/i }).click()
                cy.findByTestId('wizard-step-counter').should('contain', 'Step 3')
                cy.findByRole('button', { name: /Continue/i }).click()
            }
        })
    })
})

// const signUp = () => {
//     cy.signUp()

//     cy.visit('/demo')

//     cy.location('pathname', { timeout: 6000 }).should('eq', '/demo')

//     cy.visit('/')

//     cy.location('pathname', { timeout: 6000 }).should('eq', '/')
// }

// const logIn = () => {
//     cy.findByRole('textbox', { name: /Email address/i })
//         .type('fake@posthog.com')
//         .should('have.value', 'fake@posthog.com')
//     cy.findByLabelText(/Password/i)
//         .type('Test1234')
//         .should('have.value', 'Test1234')

//     cy.findByRole('button', { name: /Sign in/i }).click()
// }

Cypress.on('uncaught:exception', () => {
    return false
})

import '@testing-library/cypress/add-commands'

// Configure Cypress Testing Library so that it considers `data-attr` as the test id as PostHog's codebase
// uses the data-attr instead of data-testid
import { configure } from '@testing-library/cypress'
configure({ testIdAttribute: 'data-attr' })

/**
 * Attempt to create a authenticated ssesion for the given credentials through the backend API endpoints
 *
 * @param email the email address for the user to log in with
 * @param password the password of the user
 */
Cypress.Commands.add('login', (email = 'fake@posthog.com', password = 'Test1234') => {
    const loginUrl = `${Cypress.config('baseUrl')}/login`

    cy.clearCookies()
    return cy
        .request({
            url: loginUrl,
            method: 'GET',
            failOnStatusCode: false,
        })
        .then((response) => {
            expect(response.status).to.eq(200)
            cy.getCookie('csrftoken').should('exist')

            // Extract the CSRF token from GET /login response as the returned csrf-token as part of the GET or HEAD
            // response is not the one the  next POST request is expecting
            const tokenRegex = new RegExp('name="csrfmiddlewaretoken" value="(.+)">')
            if (!tokenRegex.test(response.body)) {
                throw new Error('Invalid login page response')
            }
            const [, csrfToken] = tokenRegex.exec(response.body)
            cy.log('Extracted CSRF token from page:', csrfToken)

            // cy.clearCookie('csrftoken')
            // cy.setCookie('csrftoken', csrfToken)
            cy.getCookie('csrftoken').then((cookie) => {
                cy.log('Extract CSRF token from cookie:', cookie)
                cy.request({
                    url: loginUrl,
                    method: 'POST',
                    form: true,
                    body: {
                        email,
                        password,
                        csrfmiddlewaretoken: cookie.value,
                    },
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        Referer: loginUrl,
                    },
                    followRedirect: false,
                }).then((response) => {
                    expect(response.status).to.eq(200)
                    cy.getCookie('sessionid').should('exist')
                })
            })
        })
})

/**
 * Logs in with the given login credentials through the Login form
 *  by navigating to the Login page (/login)
 *
 * @param email the email address for the user to log in with
 * @param password the password of the user
 */
Cypress.Commands.add('loginByForm', (email = 'fake@posthog.com', password = 'Test1234') => {
    // cy.visit('/login')
    // cy.location('pathname', { timeout: 6000 }).should('eq', '/login')

    cy.findByRole('textbox', { name: /Email address/i })
        .type(email)
        .should('have.value', email)

    cy.findByLabelText(/Password/i)
        .type(password)
        .should('have.value', password)

    cy.findByRole('button', { name: /Sign in/i }).click()
})

/**
 * Helper command which signs up a user with the given information
 */
Cypress.Commands.add('signUp', (signupDetails, includeNavigation = true) => {
    const {
        name = 'name',
        company = 'Hedgehogs, Inc.',
        email = 'fake@posthog.com',
        password = 'Test1234',
    } = signupDetails

    cy.location('pathname', { timeout: 6000 }).should('eq', '/signup')

    cy.findByRole('textbox', { name: /First Name/ })
        .type(name)
        .should('have.value', name)

    cy.findByLabelText(/Company or Project/i)
        .type(company)
        .should('have.value', company)

    cy.findByRole('textbox', { name: /Email/i }).type(email).should('have.value', email)

    cy.findByLabelText(/Password/i)
        .type(password)
        .should('have.value', password)

    // cy.findByRole('checkbox', { name: /Send me/i }).click()

    cy.findByRole('button', { name: /Create my account/i }).click()

    cy.location('pathname', { timeout: 6000 }).should('eq', '/insights')

    if (includeNavigation) {
        cy.signUp()

        cy.visit('/demo')

        cy.location('pathname', { timeout: 6000 }).should('eq', '/demo')

        cy.visit('/')

        cy.location('pathname', { timeout: 6000 }).should('eq', '/')
    }
})

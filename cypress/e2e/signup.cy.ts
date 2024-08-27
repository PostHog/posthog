import { decideResponse } from '../fixtures/api/decide'
import { auth } from '../productAnalytics'

const VALID_PASSWORD = 'hedgE-hog-123%'

describe('Signup', () => {
    beforeEach(() => {
        auth.logout()
        cy.visit('/signup')
    })

    it('Cannot create account with existing email', () => {
        cy.get('[data-attr=signup-email]').type('test@posthog.com').should('have.value', 'test@posthog.com')
        cy.get('[data-attr=password]').type(VALID_PASSWORD).should('have.value', VALID_PASSWORD)
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-name]').type('Jane Doe').should('have.value', 'Jane Doe')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix Movies').should('have.value', 'Hogflix Movies')
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[data-attr=signup-submit]').click()

        cy.get('.LemonBanner').should('contain', 'There is already an account with this email address.')
    })

    it('Cannot signup without required attributes', () => {
        cy.get('[data-attr=signup-start]').click()
        cy.get('.text-danger').should('contain', 'Please enter your email to continue')
        cy.get('.text-danger').should('contain', 'Please enter your password to continue')
    })

    it('Cannot signup with invalid attributes', () => {
        cy.get('[data-attr=password]').type('123').should('have.value', '123')
        cy.get('.text-danger').should('not.exist') // Validation errors not shown until first submission
        cy.get('[data-attr=signup-start]').click()
        cy.get('.text-danger').should('contain', 'Please enter your email to continue')
        cy.get('.text-danger').should('contain', 'Add another word or two')

        cy.get('[data-attr=password]').type('123 abc def')
        cy.get('.text-danger').should('not.contain', 'Add another word or two') // Validation error removed on keystroke
    })

    it('Can create user account with first name, last name and organization name', () => {
        cy.intercept('POST', '/api/signup/').as('signupRequest')

        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type(VALID_PASSWORD).should('have.value', VALID_PASSWORD)
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-name]').type('Alice Bob').should('have.value', 'Alice Bob')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix SpinOff').should('have.value', 'Hogflix SpinOff')
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[data-attr=signup-submit]').click()

        cy.wait('@signupRequest').then((interception) => {
            expect(interception.request.body).to.have.property('first_name')
            expect(interception.request.body.first_name).to.equal('Alice')
            expect(interception.request.body).to.have.property('last_name')
            expect(interception.request.body.last_name).to.equal('Bob')
            expect(interception.request.body).to.have.property('organization_name')
            expect(interception.request.body.organization_name).to.equal('Hogflix SpinOff')
        })

        // lazy regex for a guid
        cy.location('pathname').should('match', /\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    it('Can submit the signup form multiple times if there is a generic email set', () => {
        cy.intercept('POST', '/api/signup/').as('signupRequest')

        // Create initial account
        const email = `new_user+generic_error_test@posthog.com`
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type(VALID_PASSWORD).should('have.value', VALID_PASSWORD)
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-name]').type('Alice Bob').should('have.value', 'Alice Bob')
        cy.get('[data-attr=signup-submit]').click()

        cy.wait('@signupRequest').then((interception) => {
            expect(interception.request.body).to.have.property('first_name')
            expect(interception.request.body.first_name).to.equal('Alice')
            expect(interception.request.body).to.have.property('last_name')
            expect(interception.request.body.last_name).to.equal('Bob')
        })

        cy.visit('/signup')

        // Try to recreate account with same email- should fail
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type(VALID_PASSWORD).should('have.value', VALID_PASSWORD)
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-name]').type('Alice Bob').should('have.value', 'Alice Bob')
        cy.get('[data-attr=signup-submit]').click()

        cy.wait('@signupRequest').then(() => {
            cy.get('.LemonBanner').should('contain', 'There is already an account with this email address.')
        })

        cy.get('[data-attr=signup-go-back]').click()

        // Update email to generic email
        const newEmail = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.get('[data-attr=signup-email]').clear().type(newEmail).should('have.value', newEmail)
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-submit]').click()

        cy.wait('@signupRequest').then((interception) => {
            expect(interception.request.body).to.have.property('first_name')
            expect(interception.request.body.first_name).to.equal('Alice')
            expect(interception.request.body).to.have.property('last_name')
            expect(interception.request.body.last_name).to.equal('Bob')
        })

        // lazy regex for a guid
        cy.location('pathname').should('match', /\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    it('Can create user account with just a first name', () => {
        cy.intercept('POST', '/api/signup/').as('signupRequest')

        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type(VALID_PASSWORD).should('have.value', VALID_PASSWORD)
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-name]').type('Alice').should('have.value', 'Alice')
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[data-attr=signup-submit]').click()

        cy.wait('@signupRequest').then((interception) => {
            expect(interception.request.body).to.have.property('first_name')
            expect(interception.request.body.first_name).to.equal('Alice')
            expect(interception.request.body).to.not.have.property('last_name')
            expect(interception.request.body).to.not.have.property('organization_name')
        })

        // lazy regex for a guid
        cy.location('pathname').should('match', /\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    it('Can fill out all the fields on social login', () => {
        // We can't actually test the social login feature.
        // But, we can make sure the form exists as it should, and that upon submit
        // we get the expected error that no social session exists.
        cy.clearAllCookies()
        cy.visit('/organization/confirm-creation?organization_name=&first_name=Test&email=test%40posthog.com')

        cy.get('[name=email]').should('have.value', 'test@posthog.com')
        cy.get('[name=first_name]').should('have.value', 'Test')
        cy.get('[name=organization_name]').type('Hogflix SpinOff').should('have.value', 'Hogflix SpinOff')
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[type=submit]').click()
        // if there are other form issues, we'll get errors on the form, not this toast
        cy.get('.Toastify [data-attr="error-toast"]').contains('Inactive social login session.')
    })

    it('Shows redirect notice if redirecting for maintenance', () => {
        cy.intercept('**/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'redirect-signups-to-instance': 'us',
                })
            )
        )

        cy.clearAllCookies()

        cy.visit('/signup?maintenanceRedirect=true', {
            onLoad(win: Cypress.AUTWindow) {
                ;(win as any).POSTHOG_APP_CONTEXT.preflight.cloud = true
            },
        })

        cy.get('[data-attr="info-toast"]')
            .contains(
                `You've been redirected to signup on our US instance while we perform maintenance on our other instance.`
            )
            .should('be.visible')
    })
})

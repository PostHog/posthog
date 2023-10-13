import { decideResponse } from '../fixtures/api/decide'

describe('Signup', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('include', '/login')
        cy.visit('/signup')
    })

    it('Cannot create account with existing email', () => {
        cy.get('[data-attr=signup-email]').type('test@posthog.com').should('have.value', 'test@posthog.com')
        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-first-name]').type('Jane').should('have.value', 'Jane')
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
        cy.get('.text-danger').should('contain', 'Password must be at least 8 characters')

        cy.get('[data-attr=password]').type('45678901')
        cy.get('.text-danger').should('not.contain', 'Password must be at least 8 characters') // Validation error removed on keystroke
    })

    it('Can create user account', () => {
        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')
        cy.get('[data-attr=signup-start]').click()
        cy.get('[data-attr=signup-first-name]').type('Alice').should('have.value', 'Alice')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix SpinOff').should('have.value', 'Hogflix SpinOff')
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[data-attr=signup-submit]').click()

        // lazy regex for a guid
        cy.location('pathname').should('match', /\/verify_email\/[a-zA-Z0-9_.-]*/)
    })

    it('Can fill out all the fields on social login', () => {
        // We can't actually test the social login feature.
        // But, we can make sure the form exists as it should, and that upon submit
        // we get the expected error that no social session exists.
        cy.visit('/logout')
        cy.location('pathname').should('include', '/login')
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
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'redirect-signups-to-instance': 'us',
                })
            )
        )

        cy.visit('/logout')
        cy.location('pathname').should('include', '/login')

        cy.visit('/signup?maintenanceRedirect=true', {
            onLoad(win: Cypress.AUTWindow) {
                win.POSTHOG_APP_CONTEXT.preflight.cloud = true
            },
        })

        cy.get('[data-attr="info-toast"]')
            .contains(
                `You've been redirected to signup on our US instance while we perform maintenance on our other instance.`
            )
            .should('be.visible')
    })
})

import { auth } from '../support'

describe('Auth', () => {
    it('Logout', () => {
        auth.logout()
    })

    it('Logout and login', () => {
        auth.logout()

        cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)

        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

        cy.get('[type=submit]').click()
        // Login should have succeeded
        cy.location('pathname').should('eq', '/')
    })

    it('Logout and verify that Google login button has correct link', () => {
        auth.logout()

        cy.window().then((win) => {
            win.POSTHOG_APP_CONTEXT.preflight.available_social_auth_providers = {
                'google-oauth2': true,
            }
        })

        cy.get('a[href="/login/google-oauth2/"').should('exist') // As of March 2023, the trailing slash really matters!
    })

    it('Try logging in improperly and then properly', () => {
        auth.logout()

        cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
        cy.get('[data-attr=password]').type('wrong password').should('have.value', 'wrong password')
        cy.get('[type=submit]').click()
        // There should be an error message now
        cy.get('.LemonBanner').should('contain', 'Invalid email or password.')
        // Now try with the right password
        cy.get('[data-attr=password]').clear().type('12345678')
        cy.get('[type=submit]').click()
        // Login should have succeeded
        cy.location('pathname').should('eq', '/')
    })

    it('Redirect to appropriate place after login', () => {
        auth.logout()

        cy.visit('/activity/explore')
        cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

        cy.get('[data-attr=login-email]').type('test@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
        cy.get('[data-attr=password]').type('12345678')
        cy.get('[type=submit]').click()

        cy.location('pathname').should('include', '/activity/explore')
    })

    it('Redirect to appropriate place after login with complex URL', () => {
        auth.logout()

        cy.visit('/insights?search=testString')
        cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

        cy.get('[data-attr=login-email]').type('test@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
        cy.get('[data-attr=password]').type('12345678')
        cy.get('[type=submit]').click()

        cy.location('search').should('include', 'testString')
        cy.get('.saved-insight-empty-state').should('contain', 'testString') // Ensure the URL was properly parsed and components shown correctly
    })

    it('Cannot access signup page if authenticated', () => {
        cy.visit('/signup')
        cy.location('pathname').should('eq', '/project/1')
    })
})

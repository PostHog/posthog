import { urls } from 'scenes/urls'
import { combineUrl } from 'kea-router'
import { InsightType } from '../../frontend/src/types'

describe('Auth', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-menu-toggle]').click()
    })

    it('Logout', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('eq', '/login')
    })

    it('Logout and login', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('[data-attr=login-email]').type('fake@posthog.com').should('have.value', 'fake@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)

        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

        cy.get('[type=submit]').click()
    })

    it('Try logging in improperly', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('[data-attr=login-email]').type('fake@posthog.com').should('have.value', 'fake@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
        cy.get('[data-attr=password]').type('wrong password').should('have.value', 'wrong password')
        cy.get('[type=submit]').click()

        cy.get('.inline-message.danger').should('contain', 'Invalid email or password.')
    })

    it('Redirect to appropriate place after login', () => {
        cy.visit('/logout')
        cy.location('pathname').should('include', '/login')

        cy.visit('/events')
        cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

        cy.get('[data-attr=login-email]').type('test@posthog.com').blur()
        cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
        cy.get('[data-attr=password]').type('12345678')
        cy.get('[type=submit]').click()

        cy.location('pathname').should('include', '/events')
    })

    it('Redirect to appropriate place after login with complex URL', () => {
        cy.visit('/logout')
        cy.location('pathname').should('include', '/login')

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
        cy.location('pathname').should('eq', urls.projectHomepage())
    })
})

describe('Password Reset', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('eq', '/login')
    })

    it('Can request password reset', () => {
        cy.get('[data-attr="forgot-password"]').click()
        cy.location('pathname').should('eq', '/reset')
        cy.get('[data-attr="reset-email"]').type('test@posthog.com')
        cy.get('button[type=submit]').click()
        cy.get('div').should('contain', 'Request received successfully!')
        cy.get('b').should('contain', 'test@posthog.com')
    })

    it('Cannot reset with invalid token', () => {
        cy.visit('/reset/user_id/token')
        cy.get('div').should('contain', 'The provided link is invalid or has expired. ')
    })

    it('Shows validation error if passwords do not match', () => {
        cy.visit('/reset/e2e_test_user/e2e_test_token')
        cy.get('#password').type('12345678')
        cy.get('.ant-progress-bg').should('be.visible')
        cy.get('#passwordConfirm').type('1234567A')
        cy.get('button[type=submit]').click()
        cy.get('.inline-message.danger').should('contain', 'Password confirmation does not match.')
        cy.location('pathname').should('eq', '/reset/e2e_test_user/e2e_test_token') // not going anywhere
    })

    it('Shows validation error if password is too short', () => {
        cy.visit('/reset/e2e_test_user/e2e_test_token')
        cy.get('#password').type('123')
        cy.get('#passwordConfirm').type('123')
        cy.get('button[type=submit]').click()
        cy.get('.ant-form-item-explain-error').should('be.visible')
        cy.get('.ant-form-item-explain-error').should('contain', 'must be at least 8 characters')
        cy.location('pathname').should('eq', '/reset/e2e_test_user/e2e_test_token') // not going anywhere
    })

    it('Can reset password with valid token', () => {
        cy.visit('/reset/e2e_test_user/e2e_test_token')
        cy.get('#password').type('NEW123456789')
        cy.get('#passwordConfirm').type('NEW123456789')
        cy.get('button[type=submit]').click()
        cy.get('.Toastify__toast--success').should('be.visible')

        // assert the user was redirected; can't test actual redirection to /insights because the test handler doesn't actually log in the user
        cy.location('pathname').should('not.contain', '/reset/e2e_test_user/e2e_test_token')
    })
})

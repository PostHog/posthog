import { auth } from '../productAnalytics'

const VALID_PASSWORD = 'hedgE-hog-123%'

describe('Password Reset', () => {
    beforeEach(() => {
        auth.logout()
    })

    it('Can request password reset', () => {
        cy.get('[data-attr=login-email]').type('fake@posthog.com').should('have.value', 'fake@posthog.com').blur()
        cy.get('[data-attr=forgot-password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
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
        cy.get('[data-attr="password"]').type(VALID_PASSWORD)
        cy.get('.LemonProgress__track').should('be.visible')
        cy.get('[data-attr="password-confirm"]').type('1234567A')
        cy.get('button[type=submit]').click()
        cy.get('.text-danger').should('contain', 'Passwords do not match')
        cy.location('pathname').should('eq', '/reset/e2e_test_user/e2e_test_token') // not going anywhere
    })

    it('Shows validation error if password is too short', () => {
        cy.visit('/reset/e2e_test_user/e2e_test_token')
        cy.get('[data-attr="password"]').type('123')
        cy.get('[data-attr="password-confirm"]').type('123')
        cy.get('button[type=submit]').click()
        cy.get('.text-danger').should('be.visible')
        cy.get('.text-danger').should('contain', 'Add another word or two')
        cy.location('pathname').should('eq', '/reset/e2e_test_user/e2e_test_token') // not going anywhere
    })

    it('Can reset password with valid token', () => {
        cy.visit('/reset/e2e_test_user/e2e_test_token')
        cy.get('[data-attr="password"]').type(VALID_PASSWORD)
        cy.get('[data-attr="password-confirm"]').type(VALID_PASSWORD)
        cy.get('button[type=submit]').click()
        cy.get('.Toastify__toast--success').should('be.visible')

        // assert the user was redirected; can't test actual redirection to /insights because the test handler doesn't actually log in the user
        cy.location('pathname').should('not.contain', '/reset/e2e_test_user/e2e_test_token')
    })
})

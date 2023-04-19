// import { urls } from 'scenes/urls'

// describe('Auth', () => {
//     beforeEach(() => {
//         cy.get('[data-attr=top-menu-toggle]').click()
//     })

//     it('Logout', () => {
//         cy.get('[data-attr=top-menu-item-logout]').click()
//         cy.location('pathname').should('eq', '/login')
//     })

//     it('Logout and login', () => {
//         cy.get('[data-attr=top-menu-item-logout]').click()

//         cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()
//         cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)

//         cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

//         cy.get('[type=submit]').click()
//         // Login should have succeeded
//         cy.location('pathname').should('eq', '/home')
//     })

//     it('Logout and verify that Google login button has correct link', () => {
//         cy.get('[data-attr=top-menu-item-logout]').click()

//         cy.window().then((win) => {
//             win.POSTHOG_APP_CONTEXT.preflight.available_social_auth_providers = {
//                 'google-oauth2': true,
//             }
//         })

//         cy.get('a[href="/login/google-oauth2/"').should('exist') // As of March 2023, the trailing slash really matters!
//     })

//     it('Try logging in improperly and then properly', () => {
//         cy.get('[data-attr=top-menu-item-logout]').click()

//         cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()
//         cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
//         cy.get('[data-attr=password]').type('wrong password').should('have.value', 'wrong password')
//         cy.get('[type=submit]').click()
//         // There should be an error message now
//         cy.get('.LemonBanner').should('contain', 'Invalid email or password.')
//         // Now try with the right password
//         cy.get('[data-attr=password]').clear().type('12345678')
//         cy.get('[type=submit]').click()
//         // Login should have succeeded
//         cy.location('pathname').should('eq', '/home')
//     })

//     it('Redirect to appropriate place after login', () => {
//         cy.visit('/logout')
//         cy.location('pathname').should('include', '/login')

//         cy.visit('/events')
//         cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

//         cy.get('[data-attr=login-email]').type('test@posthog.com').blur()
//         cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
//         cy.get('[data-attr=password]').type('12345678')
//         cy.get('[type=submit]').click()

//         cy.location('pathname').should('include', '/events')
//     })

//     it('Redirect to appropriate place after login with complex URL', () => {
//         cy.visit('/logout')
//         cy.location('pathname').should('include', '/login')

//         cy.visit('/insights?search=testString')
//         cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

//         cy.get('[data-attr=login-email]').type('test@posthog.com').blur()
//         cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
//         cy.get('[data-attr=password]').type('12345678')
//         cy.get('[type=submit]').click()

//         cy.location('search').should('include', 'testString')
//         cy.get('.saved-insight-empty-state').should('contain', 'testString') // Ensure the URL was properly parsed and components shown correctly
//     })

//     it('Cannot access signup page if authenticated', () => {
//         cy.visit('/signup')
//         cy.location('pathname').should('eq', urls.projectHomepage())
//     })
// })

// describe('Password Reset', () => {
//     beforeEach(() => {
//         cy.get('[data-attr=top-menu-toggle]').click()
//         cy.get('[data-attr=top-menu-item-logout]').click()
//         cy.location('pathname').should('eq', '/login')
//     })

//     it('Can request password reset', () => {
//         cy.get('[data-attr=login-email]').type('fake@posthog.com').should('have.value', 'fake@posthog.com').blur()
//         cy.get('[data-attr=forgot-password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
//         cy.get('[data-attr="forgot-password"]').click()
//         cy.location('pathname').should('eq', '/reset')
//         cy.get('[data-attr="reset-email"]').type('test@posthog.com')
//         cy.get('button[type=submit]').click()
//         cy.get('div').should('contain', 'Request received successfully!')
//         cy.get('b').should('contain', 'test@posthog.com')
//     })

//     it('Cannot reset with invalid token', () => {
//         cy.visit('/reset/user_id/token')
//         cy.get('div').should('contain', 'The provided link is invalid or has expired. ')
//     })

//     it('Shows validation error if passwords do not match', () => {
//         cy.visit('/reset/e2e_test_user/e2e_test_token')
//         cy.get('[data-attr="password"]').type('12345678')
//         cy.get('.ant-progress-bg').should('be.visible')
//         cy.get('[data-attr="password-confirm"]').type('1234567A')
//         cy.get('button[type=submit]').click()
//         cy.get('.text-danger').should('contain', 'Passwords do not match')
//         cy.location('pathname').should('eq', '/reset/e2e_test_user/e2e_test_token') // not going anywhere
//     })

//     it('Shows validation error if password is too short', () => {
//         cy.visit('/reset/e2e_test_user/e2e_test_token')
//         cy.get('[data-attr="password"]').type('123')
//         cy.get('[data-attr="password-confirm"]').type('123')
//         cy.get('button[type=submit]').click()
//         cy.get('.text-danger').should('be.visible')
//         cy.get('.text-danger').should('contain', 'must be at least 8 characters')
//         cy.location('pathname').should('eq', '/reset/e2e_test_user/e2e_test_token') // not going anywhere
//     })

//     it('Can reset password with valid token', () => {
//         cy.visit('/reset/e2e_test_user/e2e_test_token')
//         cy.get('[data-attr="password"]').type('NEW123456789')
//         cy.get('[data-attr="password-confirm"]').type('NEW123456789')
//         cy.get('button[type=submit]').click()
//         cy.get('.Toastify__toast--success').should('be.visible')

//         // assert the user was redirected; can't test actual redirection to /insights because the test handler doesn't actually log in the user
//         cy.location('pathname').should('not.contain', '/reset/e2e_test_user/e2e_test_token')
//     })
// })

const subdomain = 'app'

describe('Redirect to logged in instance', () => {
    beforeEach(() => {
        cy.visit('/logout')

        const baseUrl = Cypress.config().baseUrl

        cy.intercept('http://app.posthogtesting.com/**', (req) => {
            req.url = req.url.replace('http://app.posthogtesting.com', baseUrl)
        })

        cy.intercept('http://eu.posthogtesting.com/**', (req) => {
            req.url = req.url.replace('http://eu.posthogtesting.com', baseUrl)
        })

        cy.intercept(`http://app.localhost:8000/**`, (req) => {
            req.url = req.url.replace('http://app.localhost:8000', baseUrl)
        })
    })

    it('Redirects to logged in instance', () => {
        // visit the url and mock the document.cookie
        const redirect_path = '/test'
        cy.visit(`/login?next=${redirect_path}`)
        cy.setCookie('ph_current_instance', `${subdomain}.posthog.com`)
        cy.setCookie('is-logged-in', '1')
        cy.reload()

        // check the url subdomain starts with app
        cy.location('hostname').should('include', `${subdomain}.`)
        // check the url path is correct
        cy.location('pathname').should('eq', redirect_path)

        // cy.setCookie('is-logged-in', '1')

        // cy.getCookie('ph_current_instance').should('have.property', 'value', 'eu.posthog.com')

        // cy.reload()

        // cy.visit('/logout')
        // cy.route('GET', 'https://app.posthog.com/').as('app')
        // cy.visit('/login')

        // // Mock the cookies
        // cy.setCookie('ph_current_instance', 'eu.posthog.com')
        // cy.setCookie('is-logged-in', '1')
        // cy.visit('/login?next=/test')

        // cy.wait(5000)
    })
})

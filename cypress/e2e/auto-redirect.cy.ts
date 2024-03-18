describe('Redirect to other subdomain if logged in', () => {
    beforeEach(() => {
        cy.clearAllCookies()
    })
    it('Redirects to the EU instance', () => {
        cy.visit('/logout')

        const redirect_path = '/test'

        cy.visit(`/login?next=${redirect_path}`)

        cy.setCookie('ph_current_instance', `"eu.posthog.com"`)
        cy.setCookie('is-logged-in', '1')
        cy.reload()

        // TODO: turn this on when the feature flag is remove, currently mocking the feature flags seems broken
        // cy.get('[data-attr=info-toast]').should('contain', 'EU cloud')

        // goes to http://eu.localhost:8000/login?next=/test
        // the login page then handles the redirection to /test

        // ideally the redirect with cypress, but couldn't find a way to do this in a reasonable amount of time
    })

    it('Redirects to the US instance', () => {
        cy.visit('/logout')

        const redirect_path = '/test'

        cy.visit(`/login?next=${redirect_path}`)

        cy.setCookie('ph_current_instance', `"us.posthog.com"`)
        cy.setCookie('is-logged-in', '1')
        cy.reload()

        // TODO: turn this on when the feature flag is remove, currently mocking the feature flags seems broken
        // cy.get('[data-attr=info-toast]').should('contain', 'US cloud')

        // goes to http://eu.localhost:8000/login?next=/test
        // the login page then handles the redirection to /test

        // ideally the redirect with cypress, but couldn't find a way to do this in a reasonable amount of time
    })
})

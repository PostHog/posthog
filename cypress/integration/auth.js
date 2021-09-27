describe('Auth', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-navigation-whoami]').click()
    })

    it('Logout', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('eq', '/login')
    })

    it('Logout and login', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('[data-attr=login-email]').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

        cy.get('[type=submit]').click()
    })

    it('Try logging in improperly', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('[data-attr=login-email]').type('fake@posthog.com').should('have.value', 'fake@posthog.com')
        cy.get('[data-attr=password]').type('wrong password').should('have.value', 'wrong password')
        cy.get('[type=submit]').click()

        cy.get('.error-message').should('contain', 'Invalid email or password.')
    })

    it('Redirect to appropriate place after login', () => {
        cy.visit('/logout')
        cy.location('pathname').should('include', '/login')

        cy.visit('/events')
        cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

        cy.get('[data-attr=login-email]').type('test@posthog.com')
        cy.get('[data-attr=password]').type('12345678')
        cy.get('[type=submit]').click()

        cy.location('pathname').should('include', '/events')
    })

    it('Redirect to appropriate place after login with complex URL', () => {
        cy.visit('/logout')
        cy.location('pathname').should('include', '/login')

        cy.visit(
            '/insights?insight=TRENDS&interval=day&display=ActionsLineGraph&actions=%5B%5D&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%2C%7B"id"%3A"%24autocapture"%2C"name"%3A"%24autocapture"%2C"type"%3A"events"%2C"order"%3A1%7D%5D&properties=%5B%5D&filter_test_accounts=false&new_entity=%5B%5D'
        )
        cy.location('pathname').should('include', '/login') // Should be redirected to login because we're now logged out

        cy.get('[data-attr=login-email]').type('test@posthog.com')
        cy.get('[data-attr=password]').type('12345678')
        cy.get('[type=submit]').click()

        cy.location('search').should('include', 'autocapture')
        cy.get('[data-attr=trend-element-subject-1]').should('contain', 'Autocapture') // Ensure the URL was properly parsed and components shown correctly
    })

    it('Cannot access signup page if authenticated', () => {
        cy.visit('/signup')
        cy.location('pathname').should('eq', '/insights')
    })
})

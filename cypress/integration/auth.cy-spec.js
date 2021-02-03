describe('Auth', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-navigation-whoami]').click()
    })

    it('Logout', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('include', '/login')
    })

    it('Logout and login', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

        cy.get('#inputPassword').type('12345678').should('have.value', '12345678')

        cy.get('.btn').click()
    })

    it('Try logging in improperly', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

        cy.get('#inputPassword').type('wrong password').should('have.value', 'wrong password')

        cy.get('.btn').click()

        cy.get('[data-attr=login-error]').should('exist')
    })
})

describe('Auth', () => {
    it('Logout', () => {
        cy.get('[data-attr=user-options-dropdown]').trigger('mouseover')
        cy.get('[data-attr=user-options-logout]').click()
    })

    it('Logout and login', () => {
        cy.get('[data-attr=user-options-dropdown]').trigger('mouseover')
        cy.get('[data-attr=user-options-logout]').click()

        cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

        cy.get('#inputPassword').type('password').should('have.value', 'password')

        cy.get('.btn').click()
    })

    it('Try logging in improperly', () => {
        cy.get('[data-attr=user-options-dropdown]').trigger('mouseover')
        cy.get('[data-attr=user-options-logout]').click()

        cy.get('#inputEmail').type('fake@posthog.com').should('have.value', 'fake@posthog.com')

        cy.get('#inputPassword').type('wrong password').should('have.value', 'wrong password')

        cy.get('.btn').click()

        cy.get('[data-attr=login-error]').should('exist')
    })
})

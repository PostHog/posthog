describe('Auth', () => {
    it('Logout', () => {
        cy.findByTestId('user-options-dropdown').trigger('mouseover')
        cy.findByRole('link', { name: /Logout/i })
            .should('exist')
            .click()
        cy.location('pathname', { timeout: 6000 }).should('eq', '/login')
    })

    it('Logout and login', () => {
        cy.findByTestId('user-options-dropdown').trigger('mouseover')
        cy.findByRole('link', { name: /Logout/i })
            .should('exist')
            .click()

        cy.location('pathname', { timeout: 6000 }).should('eq', '/login')

        cy.loginByForm()

        cy.location('pathname', { timeout: 6000 }).should('eq', '/insights')
    })

    it('Try logging in improperly', () => {
        cy.findByTestId('user-options-dropdown').trigger('mouseover')
        cy.findByRole('link', { name: /Logout/i })
            .should('exist')
            .click()

        cy.loginByForm('fake@posthog.com', 'wrong password')

        cy.findByText(/Your username and password didn't match. Please try again./i)
    })
})

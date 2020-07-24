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

    it('Sign up using team link', () => {
        cy.get('[data-attr=menu-item-team]').click()
        cy.get('[data-attr=copy-invite-to-clipboard-input]')
            .invoke('val')
            .then((link) => {
                cy.get('[data-attr=user-options-dropdown]').trigger('mouseover')
                cy.get('[data-attr=user-options-logout]').click()
                cy.visit(link)

                cy.get('#inputName').type(Cypress._.random(0, 1e6))

                cy.get('#inputEmail').type(Cypress._.random(0, 1e6) + '@posthog.com')

                cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

                cy.get('.btn').click()

                cy.get('[data-attr=trend-line-graph]').should('exist') //on trends page
            })
    })

    it('Sign up using team link with updates', () => {
        cy.get('[data-attr=menu-item-team]').click()
        cy.get('[data-attr=copy-invite-to-clipboard-input]')
            .invoke('val')
            .then((link) => {
                cy.get('[data-attr=user-options-dropdown]').trigger('mouseover')
                cy.get('[data-attr=user-options-logout]').click()
                cy.visit(link)

                cy.get('#inputName').type(Cypress._.random(0, 1e6))

                cy.get('#inputEmail').type(Cypress._.random(0, 1e6) + '@posthog.com')

                cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

                cy.get('[data-attr=updates-checkbox').check()

                cy.get('.btn').click()

                cy.get('[data-attr=trend-line-graph]').should('exist') //on trends page
            })
    })
})

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

    it('Create and use invite', () => {
        cy.get('[data-attr=menu-item-organization]').click()
        cy.get('[data-attr=invite-teammate-button]').click()
        cy.get('[data-attr=invite-email-input]').type('faux@posthog.com')
        cy.get('.ant-modal-footer > .ant-btn-primary').click()
        cy.get('[data-attr=invite-link]')
            .invoke('val')
            .then((linkElement) => {
                cy.get('[data-attr=user-options-dropdown]').trigger('mouseover')
                cy.get('[data-attr=user-options-logout]').click()
                console.log(linkElement)
                cy.visit(linkElement.get(0).innerText)

                cy.get('#inputName').type(Cypress._.random(0, 1e6))

                cy.get('#inputEmail').type('faux@posthog.com')

                cy.get('#inputPassword').type('Test1234').should('have.value', 'Test1234')

                cy.get('.btn').click()

                cy.get('[data-attr=trend-line-graph]').should('exist') //on trends page
            })
    })
})

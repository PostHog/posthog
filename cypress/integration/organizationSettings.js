describe('Organization settings', () => {
    it('can navigate to organization settings and invite/change users', () => {
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/organization/settings')
        cy.get('.page-title').should('contain', 'Organization')

        // Click "Invite team member"
        cy.get('[data-attr=invite-teammate-button]').first().click()
        // Enter invite the user
        cy.get('[data-attr=invite-email-input]').type(`fake+${Math.floor(Math.random() * 10000)}@posthog.com`)
        cy.get('[data-attr=invite-team-member-submit]').click()

        // Log in as invited user
        cy.get('[data-attr=invite-link]')
            .last()
            .then((element) => {
                cy.get('[data-attr=top-navigation-whoami]').click()
                cy.get('[data-attr=top-menu-item-logout]').click()
                cy.visit(element.text())
            })
        cy.get('#password').type('12345678')
        cy.get('#first_name').type('Bob')
        cy.get('[data-attr=password-signup]').click()
        cy.get('.Toastify__toast-body').should('contain', 'You have joined')
        cy.location('pathname').should('include', '/insights')

        // Log out, log in as main
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.login()

        // Go to organization settings
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/organization/settings')
        cy.get('.page-title').should('contain', 'Organization')

        // Change membership level
        cy.get('[data-attr=change-membership-level]').last().should('contain', 'member')
        cy.get('[data-attr=change-membership-level]').last().click()
        cy.get('[data-test-level=8]').click()
        cy.get('[data-attr=change-membership-level]').last().should('contain', 'administrator')

        // Delete member
        cy.get('[data-attr=delete-org-membership]').last().click()
        cy.get('.ant-modal-confirm-btns button').last().click()
        cy.get('.Toastify__toast-body').should('contain', 'Removed Bob from organization')
    })
})

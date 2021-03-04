describe('Invite Signup', () => {
    it('Creates an invite ', () => {
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-org-settings').click()
        cy.get('[data-attr=invite-teammate-button]').click()

        cy.get('[data-attr=invite-email-input]').type('newuser@posthog.com')
        cy.get('[data-attr=invite-team-member-submit]').click()

        cy.get('.Toastify__toast-body h1').should('contain', 'Invite sent!')
        cy.get('.invites-table tbody td:first-of-type').should('contain', 'newuser@posthog.com')

        // Logged in user cannot accept invite for someone else
        cy.get('.invites-table tbody td:nth-last-child(2)').then((element) => {
            cy.log('Hiya there!')
            cy.log(element)
            cy.log(element.get(0).innerText)
            cy.visit(element.text())
        })
        cy.get('.error-view-container').should('exist')
        cy.get('h1.page-title').should('contain', 'Oops! You cannot use this invite link')
        cy.get('.error-message div').should('contain', 'This invite is intended for another email address')
    })
})

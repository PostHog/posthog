describe('Organization settings', () => {
    it('can navigate to organization settings', () => {
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/organization/members')
    })
})

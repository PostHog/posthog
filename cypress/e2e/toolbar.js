describe('Toolbar', () => {
    it('Toolbar loads', () => {
        cy.visit('/demo')
        cy.get('#__POSTHOG_TOOLBAR__').should('exist')
    })

    it.only('toolbar item in sidebar has launch options', () => {
        cy.get('[data-attr="menu-item-toolbar-launch"]').click()
        cy.get('[data-attr="sidebar-launch-toolbar"]').contains('Add toolbar URL').click()
        cy.location('pathname').should('include', '/toolbar')
    })
})

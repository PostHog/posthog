describe('Toolbar', () => {
    it('Toolbar loads', () => {
        cy.get('[data-attr="menu-item-toolbar-launch"]').click()
        cy.get('[data-attr="sidebar-launch-toolbar"]').contains('Add toolbar URL').click()
        cy.location().then((loc) => {
            cy.get('[data-attr="url-input"]').clear().type(`http://${loc.host}/demo`)
            cy.get('[data-attr="url-save"]').click()
            cy.get('[data-attr="toolbar-open"]')
                .first()
                .parent()
                .invoke('attr', 'href')
                .then((href) => {
                    cy.visit(href)
                })
            cy.get('#__POSTHOG_TOOLBAR__').shadow().find('div').should('exist')
        })
    })

    it('toolbar item in sidebar has launch options', () => {
        cy.get('[data-attr="menu-item-toolbar-launch"]').click()
        cy.get('[data-attr="sidebar-launch-toolbar"]').contains('Add toolbar URL').click()
        cy.location('pathname').should('include', '/toolbar')
    })
})

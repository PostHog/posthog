describe('Toolbar', () => {
    it('Toolbar loads', () => {
        cy.get('[data-attr="menu-item-toolbarlaunch"]').click()
        cy.contains('Add authorized URL').click()
        cy.location().then((loc) => {
            cy.get('[data-attr="url-input"]').clear().type(`http://${loc.host}/demo`)
            cy.get('[data-attr="url-save"]').click()
            cy.get('[data-attr="toolbar-open"]')
                .first()
                .invoke('attr', 'href')
                .then((href) => {
                    cy.visit(href)
                })
            cy.get('#__POSTHOG_TOOLBAR__').shadow().find('.Toolbar').should('exist')
        })
    })

    it('toolbar item in sidebar has launch options', () => {
        cy.get('[data-attr="menu-item-toolbarlaunch"]').click()
        cy.contains('Add authorized URL').click()
        cy.location('pathname').should('include', '/toolbar')
    })
})

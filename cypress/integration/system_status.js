describe('System Status', () => {
    it('System Status loaded', () => {
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=menu-item-system-status]').click()
        cy.get('h1').should('contain', 'System Status')
    })
})

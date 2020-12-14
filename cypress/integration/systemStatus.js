describe('System Status', () => {
    it('System Status loaded', () => {
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=menu-item-instance-status]').click()
        cy.get('h1').should('contain', 'System Status')
        cy.get('table').should('contain', 'Postgres events table')
        cy.get('table').should('contain', 'Redis current queue depth')
    })
})

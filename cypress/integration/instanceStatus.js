describe('System Status', () => {
    it('System Status loaded', () => {
        cy.get('[data-attr=menu-item-instance]').click()
        cy.get('[data-attr=menu-item-instance-status]').click()
        cy.get('h1').should('contain', 'System Status')
        cy.get('table').should('contain', 'Postgres Event table')
        cy.get('table').should('contain', 'Redis current queue depth')
    })
})

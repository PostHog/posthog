describe('Systems Status', () => {
    it('Systems Status loaded', () => {
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=menu-item-system-status]').click()
        cy.get('h1').should('contain', 'Systems Status')
        cy.get('table').should('contain', 'Postgres Event table')
        cy.get('table').should('contain', 'Redis current queue depth')
    })
})

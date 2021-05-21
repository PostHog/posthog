describe('System Status', () => {
    it('System Status loaded', () => {
        cy.location('pathname').should('eq', '/insights')
        cy.wait(500)
        cy.get('[data-attr=system-status-badge]').click()
        cy.get('h1').should('contain', 'System Status')
        cy.get('table').should('contain', 'Postgres events table')
    })
})

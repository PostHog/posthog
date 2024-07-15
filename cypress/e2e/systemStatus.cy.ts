describe('System Status', () => {
    it('System Status loaded', () => {
        cy.location('pathname').should('eq', '/project/1/insights')
        cy.wait(500)
        cy.get('[data-attr=menu-item-me]').click()
        cy.get('[data-attr=top-menu-instance-panel]').click()
        cy.get('h1').should('contain', 'Instance panel')
        cy.get('table').should('contain', 'Events in ClickHouse')
    })
})

describe('Sidebar', () => {
    it('A pinned dashboard should exist', () => {
        cy.get('[data-attr=pinned-dashboard-0]').should('be.visible')
    })
})

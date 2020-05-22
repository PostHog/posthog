describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-dashboards]').click()
        cy.location('pathname', { timeout: 6000 }).should('include', '/dashboard')
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
    })
})

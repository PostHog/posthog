describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-dashboards]').click()
        cy.location('pathname', { timeout: 6000 }).should('include', '/dashboard')
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
    })

    it('Click on a dashboard', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0]').should('exist')
    })
})

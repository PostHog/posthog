describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-dashboards]').click()
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
    })

    it('Click on a dashboard', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0]').should('exist')
    })
})

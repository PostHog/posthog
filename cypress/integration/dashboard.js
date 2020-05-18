describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[dataattr=menu-item-dashboards]').click()
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
    })
})

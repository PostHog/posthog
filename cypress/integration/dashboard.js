describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[dataattr=menu-item-dashboards]').click()
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
    })

    it('Should have default dashboard', () => {
        cy.get('[data-row-key="1"] > :nth-child(2) > a').click()
        cy.get('.ant-select-selector').should('contain', 'Default')
    })
})

describe('Dashboards', () => {
    beforeEach(() => {
        cy.get(':nth-child(3) > .ant-menu-submenu-title').click()
    })

    it('Dashboards loaded', () => {
        cy.wait(500)
        cy.get('h1').contains('Dashboards')
    })

    it('Should have default dashboard', () => {
        cy.get('[data-row-key="1"] > :nth-child(2) > a').click()
        cy.get('.ant-select-selector').contains('Default')
    })
})

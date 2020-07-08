describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-dashboards]').click()
        cy.location('pathname', { timeout: 6000 }).should('include', '/dashboard')
    })

    // it('Dashboards loaded', () => {
    //     cy.get('h1').should('contain', 'Dashboards')
    // })

    // it('Click on a dashboard', () => {
    //     cy.get('[data-attr=dashboard-name-0]').click()
    //     cy.get('[data-attr=dashboard-item-0]').should('exist')
    // })

    // it('Click on a dashboard item dropdown and view graph', () => {
    //     cy.get('[data-attr=dashboard-name-0]').click()
    //     cy.get('[data-attr=dashboard-item-0-dropdown]').click()
    //     cy.get('[data-attr=dashboard-item-0-dropdown-view]').click()
    //     cy.location('pathname').should('include', '/trends')
    // })

    // it('Rename dashboard item', () => {
    //     cy.get('[data-attr=dashboard-name-0]').click()
    //     cy.get('[data-attr=dashboard-item-0-dropdown]').click()
    //     cy.get('[data-attr="dashboard-item-0-dropdown-rename"]').click({ force: true })

    //     cy.get('[data-attr=modal-prompt]').clear().type('Test Name')
    //     cy.contains('OK').click()
    //     cy.contains('Test Name').should('exist')
    // })

    it('Color dashboard item', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown]').click()
        cy.get('[data-attr="dashboard-item-0-dropdown-color"]').trigger('mouseover')
        cy.get('[data-attr="dashboard-item-0-dropdown-color-1"]').click({ force: true })
        cy.get('[data-attr="dashboard-item-0"]').should(
            'have.css',
            'background',
            'rgb(38, 98, 166) none repeat scroll 0% 0% / auto padding-box border-box'
        ) //hard coded to the blue that's set
    })
})

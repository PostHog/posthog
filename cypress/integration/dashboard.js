describe('Dashboards', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-dashboards]').click()
        cy.location('pathname').should('include', '/dashboard')
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
    })

    it('Share dashboard', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0]').should('exist')

        cy.get('[data-attr=dashboard-share-button]').click()
        cy.get('[data-attr=share-dashboard-switch]').click()
        cy.get('[data-attr=share-dashboard-link]')
            .invoke('val')
            .then((link) => {
                cy.wait(200)
                cy.visit(link)
                cy.get('[data-attr="dashboard-item-title"').should('contain', 'popular browsers')
            })
    })

    it('Create an empty dashboard', () => {
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr=dashboard-name]').clear().type('YDefault')
        cy.get('button').contains('Create').click()

        cy.contains('YDefault').should('exist')
        cy.contains('There are no panels').should('exist')
    })

    it('Create dashboard from a template', () => {
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr=dashboard-name]').clear().type('XDefault')
        cy.get('[data-attr=copy-from-template]').click()
        cy.get('[data-attr=dashboard-select-default-app]').click()

        cy.get('button').contains('Create').click()

        cy.contains('XDefault').should('exist')
        cy.get('.dashboard-item').its('length').should('be.gte', 2)
    })

    it('Click on a dashboard item dropdown and view graph', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown-view]').click()
        cy.location('pathname').should('include', '/insights')
    })

    it('Rename dashboard item', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown]').click()
        cy.get('[data-attr="dashboard-item-0-dropdown-rename"]').click({ force: true })

        cy.get('[data-attr=modal-prompt]').clear().type('Test Name')
        cy.contains('OK').click()
        cy.contains('Test Name').should('exist')
    })

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

    it('Copy dashboard item', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown]').click()
        cy.get('[data-attr="dashboard-item-0-dropdown-copy"]').trigger('mouseover')
        cy.get('[data-attr="dashboard-item-0-dropdown-copy-0"]').click({ force: true })
        cy.get('[data-attr=success-toast]').should('exist')
    })

    it('Duplicate dashboard item', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown]').click()
        cy.get('[data-attr="dashboard-item-0-dropdown-duplicate"]').click({ force: true })
        cy.get('[data-attr=success-toast]').should('exist')
    })

    it('Move dashboard item', () => {
        cy.get('[data-attr=dashboard-name-0]').click()
        cy.get('[data-attr=dashboard-item-0-dropdown]').click()
        cy.get('[data-attr="dashboard-item-0-dropdown-move"]').trigger('mouseover')
        cy.get('[data-attr="dashboard-item-0-dropdown-move-0"]').click({ force: true })
        cy.get('[data-attr=success-toast]').should('exist')
    })
})

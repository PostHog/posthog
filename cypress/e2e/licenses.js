describe('Licenses', () => {
    it('Licenses loaded', () => {
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-licenses]').click()
        cy.get('[data-attr=breadcrumb-0]').should('contain', Cypress.config().baseUrl.replace('http://', '')) // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-1]').should('have.text', 'Licenses') // Breadcrumbs work
        cy.get('h1').should('contain', 'Licenses')
        cy.title().should('equal', 'Licenses • PostHog') // Page title works
    })
})

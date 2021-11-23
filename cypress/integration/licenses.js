describe('Licenses', () => {
    it('Licenses loaded', () => {
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-licenses]').click()
        cy.get('h1').should('contain', 'Licenses')
        cy.title().should('equal', 'Licenses • PostHog')
    })
})

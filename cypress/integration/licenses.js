describe('Licenses', () => {
    it('Licenses loaded', () => {
        cy.get('.whoami').click() // Top navigation dropdown
        cy.get('[data-attr=top-menu-item-licenses]').click()
        cy.get('h1').should('contain', 'Licenses')
        cy.title().should('equal', 'Instance Licenses • PostHog')
    })
})

describe('Licenses', () => {
    it('Licenses loaded', () => {
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=menu-item-licenses]').click()
        cy.get('h1').should('contain', 'Licenses')
    })
})

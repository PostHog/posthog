describe('Licenses', () => {
    it('Licenses loaded', () => {
        cy.get('[data-attr=menu-item-settings]', { timeout: 7000 }).click()
        cy.get('[data-attr=menu-item-licenses]', { timeout: 7000 }).click()
        cy.get('h1', { timeout: 7000 }).should('contain', 'Licenses')
    })
})

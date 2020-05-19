describe('Funnels', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-funnels]').click()
    })

    it('Funnels loaded', () => {
        cy.get('h1').should('contain', 'Funnels')
    })
})

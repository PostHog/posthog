describe('Paths', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-paths]').click()
    })

    it('Paths loaded', () => {
        cy.get('h1').should('contain', 'Paths')
        cy.get('[data-attr=paths-viz]').should('exist')
    })
})

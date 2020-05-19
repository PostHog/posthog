describe('Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
    })

    it('Actions loaded', () => {
        cy.get('[data-attr=menu-item-actions]').click()
        cy.get('h1').should('contain', 'Actions')
    })
})

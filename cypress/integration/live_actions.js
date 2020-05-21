describe('Live Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
        cy.get('[data-attr=menu-item-live-actions]').click()
    })

    it('Live actions loaded', () => {
        cy.get('[data-attr=live-actions-table').should('exist')
    })
})

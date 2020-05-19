describe('Live Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
    })

    it('Live actions loaded', () => {
        cy.get('[data-attr=menu-item-live-actions]').click()
        cy.get('[data-attr=live-actions-table').should('exist')
    })
})

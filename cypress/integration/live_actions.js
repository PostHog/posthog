describe('Live Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
        cy.get('[data-attr=menu-item-live-actions]').click()
    })

    it('Live actions loaded', () => {
        cy.get('[data-attr=live-actions-table').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-LiveActionsTable]').click()
        cy.contains('$current_url').click()
        cy.get('[data-attr=prop-val]').click()
        cy.contains(Cypress.config().baseUrl + '/demo/1/').click()

        cy.get('[data-attr=live-actions-table').should('exist')
    })
})

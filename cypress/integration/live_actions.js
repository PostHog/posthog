describe('Live Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
        cy.get('[data-attr=menu-item-live-actions]').click()
    })

    it('Live actions loaded', () => {
        cy.get('[data-attr=events-table').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-LiveActionsTable]').click()
        cy.get('[data-attr=prop-filter-event-0]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()

        cy.get('[data-attr=events-table').should('exist')
    })
})

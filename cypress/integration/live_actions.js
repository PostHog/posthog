describe('Live Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]', { timeout: 7000 }).click()
        cy.get('[data-attr=menu-item-live-actions]', { timeout: 7000 }).click()
    })

    it('Live actions loaded', () => {
        cy.get('[data-attr=events-table]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-LiveActionsTable]').click()
        cy.get('[data-attr=prop-filter-person-0]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()

        cy.get('[data-attr=events-table]').should('exist')
    })
})

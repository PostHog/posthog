describe('Live Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]', { timeout: 7000 }).click()
        cy.get('[data-attr=menu-item-live-actions]', { timeout: 7000 }).click()
    })

    /*     it('Live actions loaded', () => {
        cy.get('[data-attr=events-table]').should('exist')
    })
 */
    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-LiveActionsTable]').click()
        cy.get('.col > .ant-select > .ant-select-selector > .ant-select-selection-item').click() // Will later substitute for data-attr
        cy.get('[data-attr=prop-filter-event-1]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-1]').click()

        cy.get('[data-attr=events-table]').should('exist')
    })
})

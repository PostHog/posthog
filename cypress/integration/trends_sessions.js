describe('Trends sessions', () => {
    beforeEach(() => {
        // given
        cy.visit('/insights')
        cy.contains('Sessions', { timeout: 7000 }).click()
    })

    it('Sessions exists', () => {
        // then
        cy.get('[data-attr=trend-line-graph]', { timeout: 7000 }).should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-trends-sessions]').click()
        cy.get('.col > .ant-select > .ant-select-selector > .ant-select-selection-item').click() // Will later substitute for data-attr
        cy.get('[data-attr=prop-filter-event-1]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-1]').click()

        cy.get('[data-attr=trend-line-graph]', { timeout: 7000 }).should('exist')
    })

    it('Apply table filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Table').click()

        cy.get('[data-attr=trend-table-graph]', { timeout: 7000 }).should('exist')
    })

    it('Apply date filter', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Save to dashboard', () => {
        cy.get('[data-attr=save-to-dashboard-button]').click()
        cy.contains('Add panel to dashboard').click()
        cy.get('[data-attr=success-toast]').should('exist')
    })
})

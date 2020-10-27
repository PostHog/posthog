describe('Trends sessions', () => {
    beforeEach(() => {
        // given
        cy.visit('/insights')
        cy.get('[id="rc-tabs-0-tab-SESSIONS"]').click()
    })

    it('Sessions exists', () => {
        // then
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-trends-sessions]').click()
        cy.get('[data-attr=property-filter-dropdown]').click()
        cy.get('[data-attr=prop-filter-event-1]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-1]').click({ force: true })

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    /*     it('Apply table filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Table').click()

        cy.get('[data-attr=trend-table-graph]').should('exist')
    }) */

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

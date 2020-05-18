describe('Trends actions & events', () => {
    beforeEach(() => {
        // given
        cy.visit('http://localhost:8000/')
        cy.contains('Sessions').click()
    })

    it('Sessions exists', () => {
        // then
        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[dataattr=new-prop-filter-trends-sessions]').click()
        cy.contains('$current_url').click()
        cy.get('[dataattr=prop-val]').click()
        cy.contains('http://localhost:8000/demo/1/').click()

        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Apply table filter', () => {
        cy.get('[dataattr=chart-filter]').click()
        cy.contains('Table').click()

        cy.get('[dataattr=trend-table-graph]').should('exist')
    })

    it('Apply date filter', () => {
        cy.get('[dataattr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Save to dashboard', () => {
        cy.get('[dataattr=save-to-dashboard-button]').click()
        cy.contains('Add panel to dashboard').click()

        cy.get('[dataattr=success-toast]').should('exist')
    })
})

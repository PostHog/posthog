describe('Trends actions & events', () => {
    beforeEach(() => {
        // given
        cy.visit('http://localhost:8000/')
    })

    it('Add a pageview action filter', () => {
        // when
        cy.contains('Add action/event').click()
        cy.get('[dataattr=trend-element-subject-1]').click()
        cy.contains('Pageviews').click()

        // then
        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.contains('Add action/event').click()
        cy.get('[dataattr=trend-element-subject-1]').click()
        cy.contains('Pageviews').click()

        cy.get('[dataattr=new-prop-filter-trends-filters]').click()
        cy.contains('$current_url').click()
        cy.get('[dataattr=prop-val]').click()
        cy.contains('http://localhost:8000/demo/1/').click()

        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Apply interval filter', () => {
        cy.get('[dataattr=interval-filter]').click()
        cy.contains('Weekly').click()

        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Apply chart filter', () => {
        cy.get('[dataattr=chart-filter]').click()
        cy.contains('Pie').click()

        cy.get('[dataattr=trend-pie-graph]').should('exist')
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

    it('Apply volume filter', () => {
        cy.get('[dataattr=shownas-filter]').click()
        cy.get('[dataattr=shownas-volume-option]').click()

        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Apply stickiness filter', () => {
        cy.get('[dataattr=shownas-filter]').click()
        cy.get('[dataattr=shownas-stickiness-option]').click()

        cy.get('[dataattr=trend-line-graph]').should('exist')
    })

    it('Save to dashboard', () => {
        cy.get('[dataattr=save-to-dashboard-button]').click()
        cy.contains('Add panel to dashboard').click()

        cy.get('[dataattr=success-toast]').should('exist')
    })
})

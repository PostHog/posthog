describe('Trends actions & events', () => {
    beforeEach(() => {
        // given
        cy.visit('http://localhost:8000/')
    })

    it('Add a pageview action filter', () => {
        // when
        cy.contains('Add action/event').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.contains('Pageviews').click()

        // then
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.contains('Add action/event').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.contains('Pageviews').click()

        cy.get('[data-attr=new-prop-filter-trends-filters]').click()
        cy.contains('$current_url').click()
        cy.get('[data-attr=prop-val]').click()
        cy.contains('http://localhost:8000/demo/1/').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply interval filter', () => {
        cy.get('[data-attr=interval-filter]').click()
        cy.contains('Weekly').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply chart filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Pie').click()

        cy.get('[data-attr=trend-pie-graph]').should('exist')
    })

    it('Apply table filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Table').click()

        cy.get('[data-attr=trend-table-graph]').should('exist')
    })

    it('Apply date filter', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply volume filter', () => {
        cy.get('[data-attr=shownas-filter]').click()
        cy.get('[data-attr=shownas-volume-option]').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply stickiness filter', () => {
        cy.get('[data-attr=shownas-filter]').click()
        cy.get('[data-attr=shownas-stickiness-option]').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Save to dashboard', () => {
        cy.get('[data-attr=save-to-dashboard-button]').click()
        cy.contains('Add panel to dashboard').click()

        cy.get('[data-attr=success-toast]').should('exist')
    })
})

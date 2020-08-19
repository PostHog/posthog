describe('Trends actions & events', () => {
    beforeEach(() => {
        // given
        cy.visit('/')
    })

    it('Add a pageview action filter', () => {
        // when
        cy.contains('Add action/event').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.contains('Pageviews').click()

        // then
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('DAU on 1 element', () => {
        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-dau-0]').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Show property select dynamically', () => {
        cy.get('[data-attr=math-property-selector-0]').should('not.exist')
        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-avg-0]').click()
        cy.get('[data-attr=math-property-selector-0]').should('exist')
    })

    it('Apply specific filter on default pageview event', () => {
        cy.get('[data-attr=show-prop-filter-0]').click()
        cy.get('[data-attr=new-prop-filter-0-\\$pageview-filter]').click()
        cy.get('[data-attr=prop-filter-event-1]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-trends-filters]').click()
        cy.get('[data-attr=prop-filter-event-1]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()

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

    it('Apply property breakdown', () => {
        cy.get('[data-attr=add-breakdown-button]').click()
        cy.get('[data-attr=prop-breakdown-select]').click()
        cy.get('[data-attr=prop-breakdown-3]').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply all users cohort breakdown', () => {
        cy.get('[data-attr=add-breakdown-button]').click()
        cy.contains('Cohort').click()
        cy.get('[data-attr=cohort-breakdown-select]').click()
        cy.get('[data-attr=cohort-breakdown-all-users]').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Save to dashboard', () => {
        cy.get('[data-attr=save-to-dashboard-button]').click()
        cy.contains('Add panel to dashboard').click()
        // cy.wait(700) // not ideal but toast has a delay render
        cy.get('[data-attr=success-toast]', { timeout: 6000 }).should('exist')
    })
})

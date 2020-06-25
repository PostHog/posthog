describe('Trends sessions', () => {
    beforeEach(() => {
        // given
        cy.visit('/')
        cy.contains('Sessions').click()
    })

    it('Navigate from distributed sessions to /trends', () => {
        cy.get('[data-attr=sessions-filter]').click()
        cy.get('[data-attr=sessions-filter-distribution]').click()
        cy.get('[data-attr=trend-table-graph]').should('exist')
        cy.contains('Actions & Events').click()
        cy.get('[data-attr=trend-line-graph] canvas').should('exist')
    })

    it('Sessions exists', () => {
        // then
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-trends-sessions]').click()
        cy.get('[data-attr=prop-filter-event-1]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
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

    it('Save to dashboard', () => {
        cy.get('[data-attr=save-to-dashboard-button]').click()
        cy.contains('Add panel to dashboard').click()
        cy.wait(500) // not ideal but toast has a delay render
        cy.get('[data-attr=success-toast]').should('exist')
    })
})

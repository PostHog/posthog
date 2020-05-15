describe('Trends', () => {
    beforeEach(() => {
        cy.visit('http://localhost:8000/')
    })

    it('Load default page', () => {
        cy.contains('Add action/event').click()
        cy.get(':nth-child(2) > .filter-action').click()
        cy.contains('Pageviews').click()
    })

    it('Apply overall filter', () => {
        cy.contains('Add action/event').click()
        cy.get(':nth-child(2) > .filter-action').click()
        cy.contains('Pageviews').click()

        cy.get('.column > .ant-row > .ant-btn').click()
        cy.contains('$current_url').click()
        cy.get('[dataAttr=prop-val]').click()
        cy.contains('http://localhost:8000/demo/1/').click()

        cy.get('.chartjs-render-monitor').should('exist')
    })

    it('Apply interval filter', () => {
        cy.get('.float-right > :nth-child(1) > .ant-select-selector').click()
        cy.contains('Weekly').click()

        cy.get('.chartjs-render-monitor').should('exist')
    })

    it('Apply chart filter', () => {
        cy.get(':nth-child(2) > .ant-select-selector').click()
        cy.contains('Pie').click()

        cy.get('.chartjs-render-monitor').should('exist')
    })

    it('Apply date filter', () => {
        cy.get(':nth-child(3) > .ant-select-selector').click()
        cy.contains('Last 30 days').click()

        cy.get('.chartjs-render-monitor').should('exist')
    })
})

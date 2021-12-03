import { urls } from 'scenes/urls'

describe('Trends', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
        cy.location('pathname').should('include', '/edit')
    })

    it('Can load a graph from a URL directly', () => {
        // regression test, the graph wouldn't load when going directly to a URL
        cy.visit(
            '/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%5D&filter_test_accounts=false&breakdown=%24referrer&breakdown_type=event&properties=%5B%7B"key"%3A"%24current_url"%2C"value"%3A"http%3A%2F%2Fhogflix.com"%2C"operator"%3A"icontains"%2C"type"%3A"event"%7D%5D'
        )

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Add a pageview action filter', () => {
        // when
        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.contains('HogFlix homepage view').click()

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

        // Test that the math selector dropdown is shown on hover
        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-total-0]').should('be.visible')

        // Use `force = true` because clicking the element without dragging the mouse makes the dropdown disappear
        cy.get('[data-attr=math-avg-0]').click({ force: true })
        cy.get('[data-attr=math-property-select]').should('exist')
    })

    it('Apply specific filter on default pageview event', () => {
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('.property-key-info').contains('Pageview').click() // Tooltip is shown with description
        cy.get('[data-attr=trend-element-subject-0]').should('have.text', 'Pageview')

        // Apply a property filter
        cy.get('[data-attr=show-prop-filter-0]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })
        cy.get('[data-attr=trend-line-graph]', { timeout: 8000 }).should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('.property-key-info').contains('Pageview').click()
        cy.get('[data-attr=trend-element-subject-0]').should('have.text', 'Pageview')
        cy.get('[data-attr=new-prop-filter-trends-filters]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        cy.get('[data-attr=trend-line-graph]', { timeout: 8000 }).should('exist')
    })

    it('Apply interval filter', () => {
        cy.get('[data-attr=interval-filter]').click()
        cy.contains('Weekly').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply pie filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Pie').click()

        cy.get('[data-attr=trend-pie-graph]').should('exist')
    })

    it('Apply table filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Table').click()

        cy.get('[data-attr=insights-table-graph]').should('exist')

        // Select Total Count math property
        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-total-0]').click()

        // Should contain more than label column
        cy.get('[data-attr=insights-table-graph]').find('.ant-table-cell').its('length').should('be.gte', 1)
    })

    it('Apply date filter', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr="date-filter"] .ant-select-selection-item').contains('Last 30 days')
        cy.get('[data-attr=trend-line-graph]', { timeout: 10000 }).should('exist')
    })

    it('Apply property breakdown', () => {
        cy.get('[data-attr=add-breakdown-button]').click()
        cy.get('[data-attr=prop-filter-event_properties-2]').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply all users cohort breakdown', () => {
        cy.get('[data-attr=add-breakdown-button]').click()
        cy.get('[data-attr=taxonomic-tab-cohorts_with_all]').click()
        cy.contains('All Users*').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Save to dashboard', () => {
        cy.get('[data-attr=save-to-dashboard-button]').click()
        cy.get('form > .ant-select > .ant-select-selector').click()
        cy.get(':nth-child(1) > .ant-select-item-option-content').click()
        cy.contains('Add insight to dashboard').click()
        cy.wait(300) // not ideal but toast has a delay render
        cy.get('[data-attr=success-toast]').should('exist')
    })
})

import { insight } from '../productAnalytics'

describe('Trends', () => {
    beforeEach(() => {
        insight.newInsight()
    })

    it('Can load a graph from a URL directly', () => {
        cy.intercept('POST', /api\/projects\/\d+\/query\//).as('loadNewQueryInsight')

        // regression test, the graph wouldn't load when going directly to a URL
        cy.visit(
            '/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%5D&filter_test_accounts=false&breakdown=%24referrer&breakdown_type=event&properties=%5B%7B"key"%3A"%24current_url"%2C"value"%3A"http%3A%2F%2Fhogflix.com"%2C"operator"%3A"icontains"%2C"type"%3A"event"%7D%5D'
        )

        cy.wait(`@loadNewQueryInsight`)

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Add a pageview action filter', () => {
        // when
        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click().type('home')
        cy.contains('Hogflix homepage view').click()

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

        cy.get('[data-attr=math-node-property-value-0]').click('left')
        cy.get('[data-attr=math-property-select]').should('exist')
    })

    it('Select HogQL expressions', () => {
        cy.get('[data-attr=math-property-selector-0]').should('not.exist')

        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-total-0]').should('be.visible')

        cy.get('[data-attr=math-node-hogql-expression-0]').click()
        cy.get('[data-attr=math-hogql-select-0]').click()
        cy.get('.CodeEditorResizeable')
            .click()
            .type(
                '{backspace}{backspace}{backspace}{backspace}{backspace}{backspace}{backspace}{backspace}{backspace}avg(1042) * 2048'
            )
        cy.contains('Update HogQL expression').click()

        cy.get('[data-attr=chart-filter]').click()
        cy.contains('Table').click()
        cy.contains('2,134,016').should('exist')
    })

    it('Apply specific filter on default pageview event', () => {
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click().type('Pageview')
        cy.get('.taxonomic-infinite-list').find('.taxonomic-list-row').contains('Pageview').click()
        cy.get('[data-attr=trend-element-subject-0]').should('have.text', 'Pageview')

        // Apply a property filter
        cy.get('[data-attr=show-prop-filter-0]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click()

        cy.get('[data-attr=prop-val]').click()
        // cypress is odd and even though when a human clicks this the right dropdown opens
        // in the test that doesn't happen
        cy.get('body').then(($body) => {
            if ($body.find('[data-attr=prop-val-0]').length === 0) {
                cy.get('[data-attr=taxonomic-value-select]').click()
            }
        })
        cy.get('[data-attr=trend-line-graph]', { timeout: 8000 }).should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click().type('Pageview')
        cy.get('.taxonomic-infinite-list').find('.taxonomic-list-row').contains('Pageview').click()
        cy.get('[data-attr=trend-element-subject-0]').should('have.text', 'Pageview')

        cy.get('[data-attr$=add-filter-group]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click()
        cy.get('[data-attr=prop-val]').click()
        // cypress is odd and even though when a human clicks this the right dropdown opens
        // in the test that doesn't happen
        cy.get('body').then(($body) => {
            if ($body.find('[data-attr=prop-val-0]').length === 0) {
                cy.get('[data-attr=taxonomic-value-select]').click()
            }
        })
        cy.get('[data-attr=prop-val-0]').click()

        cy.get('[data-attr=trend-line-graph]', { timeout: 8000 }).should('exist')
    })

    it('Apply interval filter', () => {
        cy.get('[data-attr=interval-filter]').click()
        cy.contains('week').click()

        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply pie filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.get('.Popover').find('.LemonButton').contains('Pie').click()

        cy.get('[data-attr=trend-pie-graph]').should('exist')
    })

    it('Apply table filter', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.get('.Popover').find('.LemonButton').contains('Table').click()

        cy.get('[data-attr=insights-table-graph]').should('exist')

        // Select Total Count math property
        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-total-0]').click()

        // Should contain more than label column
        cy.get('[data-attr=insights-table-graph]').find('td').its('length').should('be.gte', 1)
    })

    it('Apply date filter', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.get('div').contains('Yesterday').should('exist').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply property breakdown', () => {
        cy.get('[data-attr=add-breakdown-button]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Apply all users cohort breakdown', () => {
        cy.get('[data-attr=add-breakdown-button]').click()
        cy.get('[data-attr=taxonomic-tab-cohorts_with_all]').click()
        cy.contains('All Users*').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Show warning on MAU math in total value insight', () => {
        cy.get('[data-attr=chart-filter]').click()
        cy.get('.Popover').find('.LemonButton').contains('Pie').click()
        cy.get('[data-attr=trend-pie-graph]').should('exist') // Make sure the pie chart is loaded before proceeding

        cy.get('[data-attr=math-selector-0]').click()
        cy.get('[data-attr=math-monthly_active-0] .LemonIcon').should('exist') // This should be the warning icon

        cy.get('[data-attr=math-monthly_active-0]').trigger('mouseenter') // Activate warning tooltip
        cy.get('.Tooltip').contains('we recommend using "Unique users" here instead').should('exist')
    })

    it('Does not show delete button on single series insight', () => {
        cy.get('[data-attr=delete-prop-filter-0]').should('not.exist')
    })
})

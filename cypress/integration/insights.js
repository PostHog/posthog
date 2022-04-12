import { urls } from 'scenes/urls'

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    it('Create new insight and save copy', () => {
        cy.visit('/saved_insights/') // Should work with trailing slash just like without it
        cy.get('[data-attr=saved-insights-new-insight-dropdown]').click()
        cy.get('[data-attr-insight-type="TRENDS"').click()

        // apply filter
        cy.get('[data-attr=new-prop-filter-trends-filters]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=expand-list-event_properties]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        // Save
        cy.get('[data-attr="insight-save-button"]').click()
        cy.get('[data-attr="insight-edit-button"]').click()

        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Insights')
        cy.get('[data-attr=breadcrumb-3]').should('not.have.text', '')

        // Save and continue editing
        cy.get('[data-attr="insight-save-dropdown"]').click()
        cy.get('[data-attr="add-action-event-button"]').click()
        cy.get('[data-attr="insight-save-dropdown"]').click()
        cy.get('[data-attr="insight-save-and-continue"]').click()
        cy.get('[data-attr="add-action-event-button"]').should('exist')

        // Add another graph series, and save as new insight
        cy.get('[data-attr="add-action-event-button"]').click()
        cy.get('[data-attr="insight-save-dropdown"]').click()
        cy.get('[data-attr="insight-save-as-new-insight"]').click()

        cy.get('.ant-modal .ant-btn-primary').click()
        cy.get('[data-attr="insight-name"]').should('contain', 'Pageview count (copy)')
        // Check we're in edit mode
        cy.get('[data-attr="insight-save-button"]').should('exist')
    })

    it('Shows not found error with invalid short URL', () => {
        cy.visit('/i/i_dont_exist')
        cy.location('pathname').should('eq', '/insights/i_dont_exist')
        cy.get('.ant-skeleton-title').should('exist')
    })

    it('Stickiness graph', () => {
        cy.get('.ant-tabs-tab').contains('Stickiness').click()
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
    })

    it('Lifecycle graph', () => {
        cy.get('[data-attr=trend-line-graph]').should('exist') // Wait until components are loaded
        cy.get('.ant-tabs-tab').contains('Lifecycle').click()
        cy.get('h4').contains('Lifecycle Toggles').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
        cy.get('[data-attr=add-action-event-button]').should('not.exist') // Can't add multiple series
    })

    it('Loads default filters correctly', () => {
        // Test that default params are set correctly even if the app doesn't start on insights
        cy.visit('/events/') // Should work with trailing slash just like without it
        cy.reload()

        cy.clickNavMenu('insight')
        cy.get('[data-attr=trend-element-subject-0] span').should('contain', 'Pageview')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })

    it('Cannot see tags or description (non-FOSS feature)', () => {
        cy.get('.insight-description').should('not.exist')
        cy.get('[data-attr=insight-tags]').should('not.exist')
    })
})

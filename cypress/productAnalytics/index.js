import { urls } from 'scenes/urls'

export function applyFilter() {
    cy.get('[data-attr=insight-filters-add-filter-group]').click()
    cy.get('[data-attr=property-select-toggle-0]').click()
    cy.get('[data-attr=taxonomic-filter-searchfield]').click()
    cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
    cy.get('[data-attr=prop-val]').click()
    cy.get('[data-attr=prop-val-0]').click({ force: true })
}

export function createANewInsight(insightName) {
    cy.visit('/saved_insights/') // Should work with trailing slash just like without it
    cy.get('[data-attr=saved-insights-new-insight-dropdown]').click()
    cy.get('[data-attr-insight-type="TRENDS"').click()

    applyFilter()

    if (insightName) {
        cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click()
        cy.get('[data-attr="insight-name"] input').type(insightName)
        cy.get('[data-attr="insight-name"] [title="Save"]').click()
    }

    cy.get('[data-attr="insight-save-button"]').click()
    // wait for save to complete and URL to change and include short id
    cy.url().should('not.include', '/new')
}

export function checkInsightIsInListView(insightName) {
    // turbo mode updated the insights list?
    cy.visit(urls.savedInsights())
    cy.contains('.saved-insights table tr', insightName).should('exist')
}

export function checkInsightIsNotInListView(insightName) {
    // turbo mode updated the insights list?
    cy.visit(urls.savedInsights())
    cy.contains('.saved-insights table tr', insightName).should('not.exist')
}

export function createDashboardFromTemplate(dashboardName) {
    cy.get('[data-attr="new-dashboard"]').click()
    cy.get('[data-attr=dashboard-name-input]').clear().type(dashboardName)
    cy.get('[data-attr=copy-from-template]').click()
    cy.get('[data-attr=dashboard-select-default-app]').click()

    cy.get('[data-attr=dashboard-submit-and-go]').click()

    cy.contains(dashboardName).should('exist')
}

export function createAndGoToEmptyDashboard(dashboardName) {
    cy.get('[data-attr="new-dashboard"]').click()
    cy.get('[data-attr=dashboard-name-input]').clear().type(dashboardName)
    cy.get('button[data-attr="dashboard-submit-and-go"]').click()
}

export function addInsightToEmptyDashboard(insightName) {
    cy.intercept('POST', /api\/projects\/\d+\/insights\//).as('postInsight')

    cy.get('[data-attr=dashboard-add-graph-header]').contains('Add insight').click()
    cy.get('[data-attr=toast-close-button]').click({ multiple: true })

    if (insightName) {
        cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click()
        cy.get('[data-attr="insight-name"] input').type(insightName)
        cy.get('[data-attr="insight-name"] [title="Save"]').click()
    }

    cy.get('[data-attr=insight-save-button]').contains('Save & add to dashboard').click()
    cy.wait('@postInsight')
}

export function addInsightToDashboard(insightName, dashboardName) {
    cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')

    cy.get('[data-attr="save-to-dashboard-button"]').click() // Open the Save to dashboard modal
    cy.contains('[data-attr="dashboard-list-item"] button').contains('Add to dashboard').first().click({ force: true }) // Add the insight to a dashboard
    cy.wait('@patchInsight').then(() => {
        cy.get('[data-attr="dashboard-list-item"] button').first().contains('Added')
        cy.get('[data-attr="dashboard-list-item"] a').first().click({ force: true }) // Go to the dashboard
        cy.get('[data-attr="insight-name"]').should('contain', insightName) // Check if the insight is there
    })
}

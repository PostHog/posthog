import { urls } from 'scenes/urls'

export const savedInsights = {
    checkInsightIsInListView: (insightName: string): void => {
        cy.visit(urls.savedInsights())
        cy.contains('.saved-insights table tr', insightName).should('exist')
    },
    checkInsightIsNotInListView: (insightName: string): void => {
        cy.visit(urls.savedInsights())
        cy.contains('.saved-insights table tr', insightName).should('not.exist')
    },
    createNewInsightOfType: (insightType: string): void => {
        cy.visit('/saved_insights/') // Should work with trailing slash just like without it
        cy.get('[data-attr=saved-insights-new-insight-dropdown]').click()
        cy.get(`[data-attr-insight-type="${insightType || 'TRENDS'}"`).click()
    },
}

export const insight = {
    applyFilter: (): void => {
        cy.get('[data-attr=insight-filters-add-filter-group]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })
    },
    editName: (insightName: string): void => {
        if (insightName) {
            cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click()
            cy.get('[data-attr="insight-name"] input').type(insightName)
            cy.get('[data-attr="insight-name"] [title="Save"]').click()
        }
    },
    save: (): void => {
        cy.get('[data-attr="insight-save-button"]').click()
        // wait for save to complete and URL to change and include short id
        cy.url().should('not.include', '/new')
    },
    create: (insightName: string, insightType: string = 'TRENDS'): void => {
        cy.get('[data-attr=menu-item-insight]').click() // Open the new insight menu in the sidebar
        cy.get(`[data-attr="sidebar-new-insights-overlay"][data-attr-insight-type="${insightType}"]`).click()
        cy.get('[data-attr="insight-save-button"]').click() // Save the insight
        cy.url().should('not.include', '/new') // wait for insight to complete and update URL
        cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
        cy.get('[data-attr="insight-name"] input').type(insightName)
        cy.get('[data-attr="insight-name"] [title="Save"]').click()
    },
    addInsightToDashboard: (dashboardName: string, options: { visitAfterAdding: boolean }): void => {
        cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')

        cy.get('[data-attr="save-to-dashboard-button"]').click()
        cy.get('[data-attr="dashboard-searchfield"]').type(dashboardName)
        cy.contains('[data-attr="dashboard-list-item"]', dashboardName).within(() => {
            // force clicks rather than mess around scrolling rows that exist into view
            cy.contains('button', 'Add to dashboard').click({ force: true })
            cy.wait('@patchInsight').then(() => {
                cy.contains('Added').should('exist')
                if (options?.visitAfterAdding) {
                    cy.contains('a', dashboardName).click({ force: true })
                }
            })
        })
    },
}

export const dashboards = {
    createDashboardFromDefaultTemplate: (dashboardName: string): void => {
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr="create-dashboard-from-template"]').click()
        cy.get('[data-attr="dashboard-name"]').contains('Product analytics').should('exist')
        cy.get('[data-attr="dashboard-name"] button').click()
        cy.get('[data-attr="dashboard-name"] input').clear().type(dashboardName).blur()
        cy.contains(dashboardName).should('exist')
    },
    createAndGoToEmptyDashboard: (dashboardName: string): void => {
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr="create-dashboard-blank"]').click()
        cy.get('[data-attr="dashboard-name"]').should('exist')
        cy.get('[data-attr="dashboard-name"] button').click()
        cy.get('[data-attr="dashboard-name"] input').clear().type(dashboardName).blur()
        cy.contains(dashboardName).should('exist')
    },
    visitDashboard: (dashboardName: string): void => {
        cy.get('[placeholder="Search for dashboards"]').clear().type(dashboardName)

        cy.contains('[data-attr="dashboards-table"] tr', dashboardName).within(() => {
            cy.get('a').click()
        })
    },
}

export const dashboard = {
    addInsightToEmptyDashboard: (insightName: string): void => {
        cy.intercept('POST', /api\/projects\/\d+\/insights\//).as('postInsight')

        cy.get('[data-attr=dashboard-add-graph-header]').contains('Add insight').click()
        cy.get('[data-attr=toast-close-button]').click({ multiple: true })

        if (insightName) {
            cy.get('[data-attr="insight-name"] [data-attr="edit-prop-name"]').click()
            cy.get('[data-attr="insight-name"] input').type(insightName)
            cy.get('[data-attr="insight-name"] [title="Save"]').click()
            cy.get('h1.page-title').should('have.text', insightName)
        }

        cy.get('[data-attr=insight-save-button]').contains('Save & add to dashboard').click()
        cy.wait('@postInsight')
    },
    addAnyFilter(): void {
        cy.get('.PropertyFilterButton').should('have.length', 0)
        cy.get('[data-attr="property-filter-0"]').click()
        cy.get('[data-attr="taxonomic-filter-searchfield"]').click()
        cy.get('[data-attr="prop-filter-event_properties-1"]').click({ force: true })
        cy.get('[data-attr="prop-val"]').click()
        cy.get('[data-attr="prop-val-0"]').click({ force: true })
        cy.get('.PropertyFilterButton').should('have.length', 1)
    },
}

export function createInsight(insightName: string): void {
    savedInsights.createNewInsightOfType('TRENDS')
    insight.applyFilter()
    insight.editName(insightName)
    insight.save()
}

export function duplicateDashboardFromMenu(duplicateTiles = false): void {
    cy.contains('.LemonButton', 'Duplicate').click()
    if (duplicateTiles) {
        cy.contains('.LemonCheckbox', "Duplicate this dashboard's tiles").click()
    }
    cy.get('[data-attr="dashboard-submit-and-go"]').click()
}

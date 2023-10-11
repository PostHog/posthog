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

export function interceptInsightLoad(insightType: string): string {
    cy.intercept('GET', /api\/projects\/\d+\/insights\/trend\/\?.*/).as('loadNewTrendsInsight')
    cy.intercept('POST', /api\/projects\/\d+\/insights\/funnel\/?/).as('loadNewFunnelInsight')
    cy.intercept('GET', /api\/projects\/\d+\/insights\/retention\/\?.*/).as('loadNewRetentionInsight')
    cy.intercept('POST', /api\/projects\/\d+\/insights\/path\/?/).as('loadNewPathsInsight')
    cy.intercept('POST', /api\/projects\/\d+\/query\//).as('loadNewQueryInsight')

    let networkInterceptAlias: string = ''
    switch (insightType) {
        case 'TRENDS':
        case 'STICKINESS':
        case 'LIFECYCLE':
            networkInterceptAlias = 'loadNewTrendsInsight'
            break
        case 'FUNNELS':
            networkInterceptAlias = 'loadNewFunnelInsight'
            break
        case 'RETENTION':
            networkInterceptAlias = 'loadNewRetentionInsight'
            break
        case 'PATH':
        case 'PATHS':
            networkInterceptAlias = 'loadNewPathsInsight'
            break
        case 'SQL':
        case 'JSON':
            networkInterceptAlias = 'loadNewQueryInsight'
            break
    }

    if (networkInterceptAlias === '') {
        throw new Error('Unknown insight type: ' + insightType)
    }

    return networkInterceptAlias
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
    clickTab: (tabName: string): void => {
        const networkInterceptAlias = interceptInsightLoad(tabName)

        cy.get(`[data-attr="insight-${(tabName === 'PATHS' ? 'PATH' : tabName).toLowerCase()}-tab"]`).click()
        cy.wait(`@${networkInterceptAlias}`)
    },
    newInsight: (insightType: string = 'TRENDS'): void => {
        const networkInterceptAlias = interceptInsightLoad(insightType)

        if (insightType === 'JSON') {
            cy.clickNavMenu('savedinsights')
            cy.get('[data-attr="saved-insights-new-insight-dropdown"]').click()
            cy.get('[data-attr-insight-type="TRENDS"]').click()
            insight.clickTab('JSON')
        } else {
            cy.clickNavMenu('savedinsights')
            cy.get('[data-attr="saved-insights-new-insight-dropdown"]').click()
            cy.get(`[data-attr-insight-type="${insightType}"]`).click()
        }

        cy.wait(`@${networkInterceptAlias}`)
    },
    create: (insightName: string, insightType: string = 'TRENDS'): void => {
        cy.clickNavMenu('savedinsights')
        cy.get('[data-attr="saved-insights-new-insight-dropdown"]').click()
        cy.get(`[data-attr-insight-type="${insightType}"]`).click()

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
                cy.contains('Remove from dashboard').should('exist')
                if (options?.visitAfterAdding) {
                    cy.contains('a', dashboardName).click({ force: true })
                }
            })
        })
    },
    updateQueryEditorText(query: string, selector: string = 'query-editor'): void {
        // the default JSON query doesn't have any results, switch to one that does

        // "obviously" we need to clear the text area multiple times
        // monaco has elements in front of the text area that the human doesn't see
        // so force: true is needed everywhere
        cy.get(`[data-attr="${selector}"] textarea`).type('{selectall}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{backspace}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{selectall}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{backspace}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{selectall}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{backspace}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{selectall}', { force: true })
        cy.get(`[data-attr="${selector}"] textarea`).type('{backspace}', { force: true })

        cy.get(`[data-attr="${selector}"] textarea`).type(query, { force: true })

        // monaco adds closing squares and curlies as we type,
        // so, we need to delete any trailing characters to make valid JSON
        // 😡
        for (let i = 0; i < 10; i++) {
            cy.get(`[data-attr="${selector}"] textarea`).type('{del}', { force: true })
        }

        cy.get(`[data-attr="${selector}-save"]`).click()
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

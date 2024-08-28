import { urls } from 'scenes/urls'

import { dashboard, dashboards, insight, savedInsights } from '../productAnalytics'
import { randomString } from '../support/random'

describe('deleting dashboards', () => {
    it('can delete dashboard without deleting the insights', () => {
        cy.visit(urls.savedInsights()) // get insights list into turbo mode
        cy.clickNavMenu('dashboards')

        const dashboardName = randomString('dashboard-')
        const insightName = randomString('insight-')

        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(insightName)

        cy.get('[data-attr="dashboard-three-dots-options-menu"]').click()
        cy.get('button').contains('Delete dashboard').click()
        cy.get('[data-attr="dashboard-delete-submit"]').click()

        savedInsights.checkInsightIsInListView(insightName)
    })

    // TODO: this test works locally, just not in CI
    it.skip('can delete dashboard and delete the insights', () => {
        cy.visit(urls.savedInsights()) // get insights list into turbo mode
        cy.clickNavMenu('dashboards')

        const dashboardName = randomString('dashboard-')
        const dashboardToKeepName = randomString('dashboard-to-keep')
        const insightName = randomString('insight-')
        const insightToKeepName = randomString('insight-to-keep-')

        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(insightName)

        cy.clickNavMenu('dashboards')

        dashboards.createAndGoToEmptyDashboard(dashboardToKeepName)
        dashboard.addInsightToEmptyDashboard(insightToKeepName)

        cy.visit(urls.savedInsights())
        cy.wait('@loadInsightList').then(() => {
            cy.get('.saved-insights tr a').should('be.visible')

            // load the named insight
            cy.contains('.saved-insights tr', insightToKeepName).within(() => {
                cy.get('.Link').click()
            })

            insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

            cy.get('[data-attr="dashboard-three-dots-options-menu"]').click()
            cy.get('button').contains('Delete dashboard').click()
            cy.contains('span.LemonCheckbox', "Delete this dashboard's insights").click()
            cy.get('[data-attr="dashboard-delete-submit"]').click()

            savedInsights.checkInsightIsInListView(insightToKeepName)
            savedInsights.checkInsightIsNotInListView(insightName)
        })
    })
})

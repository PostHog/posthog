import { urls } from 'scenes/urls'

import { dashboard, dashboards, savedInsights } from '../productAnalytics'
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
})

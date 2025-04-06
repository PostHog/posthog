import { urls } from 'scenes/urls'

import { dashboard, dashboards, duplicateDashboardFromMenu, savedInsights } from '../productAnalytics'
import { randomString } from '../support/random'

describe('duplicating dashboards', () => {
    let dashboardName, insightName, expectedCopiedDashboardName, expectedCopiedInsightName

    beforeEach(() => {
        cy.intercept('POST', /\/api\/projects\/\d+\/dashboards/).as('createDashboard')

        dashboardName = randomString('dashboard-')
        expectedCopiedDashboardName = `${dashboardName} (Copy)`

        insightName = randomString('insight-')
        expectedCopiedInsightName = `${insightName} (Copy)`

        cy.visit(urls.savedInsights()) // get insights list into turbo mode
        cy.clickNavMenu('dashboards')

        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(insightName)

        cy.contains('h4', insightName).click() // get insight into turbo mode
    })

    describe('from the dashboard list', () => {
        it('can duplicate a dashboard without duplicating insights', () => {
            cy.clickNavMenu('dashboards')
            cy.get('[placeholder="Search for dashboards"]').type(dashboardName)

            cy.contains('[data-attr="dashboards-table"] tr', dashboardName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            duplicateDashboardFromMenu()
            cy.get('[data-attr="top-bar-name"] .EditableField__display').should(
                'have.text',
                expectedCopiedDashboardName
            )

            cy.wait('@createDashboard').then(() => {
                cy.get('.CardMeta h4').should('have.text', insightName).should('not.have.text', '(Copy)')
                cy.contains('h4', insightName).click()
                // this works when actually using the site, but not in Cypress
                // cy.get('[data-attr="save-to-dashboard-button"] .LemonBadge').should('have.text', '2')
            })
        })

        it('can duplicate a dashboard and duplicate insights', () => {
            cy.clickNavMenu('dashboards')
            cy.get('[placeholder="Search for dashboards"]').type(dashboardName)

            cy.contains('[data-attr="dashboards-table"] tr', dashboardName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            duplicateDashboardFromMenu(true)
            cy.get('[data-attr="top-bar-name"] .EditableField__display').should(
                'have.text',
                expectedCopiedDashboardName
            )

            cy.wait('@createDashboard').then(() => {
                cy.contains('h4', expectedCopiedInsightName).click()
                cy.get('[data-attr="save-to-dashboard-button"] .LemonBadge').should('have.text', '1')
            })

            savedInsights.checkInsightIsInListView(insightName)
            savedInsights.checkInsightIsInListView(expectedCopiedInsightName)
        })
    })

    describe('from the dashboard', () => {
        it('can duplicate a dashboard without duplicating insights', () => {
            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(dashboardName)

            cy.get('[data-attr="dashboard-three-dots-options-menu"]').click()
            duplicateDashboardFromMenu()
            cy.get('[data-attr="top-bar-name"] .EditableField__display').should(
                'have.text',
                expectedCopiedDashboardName
            )

            cy.wait('@createDashboard').then(() => {
                cy.get('.CardMeta h4').should('have.text', insightName).should('not.have.text', '(Copy)')
                cy.contains('h4', insightName).click()
                // this works when actually using the site, but not in Cypress
                // cy.get('[data-attr="save-to-dashboard-button"] .LemonBadge').should('have.text', '2')
            })
            savedInsights.checkInsightIsInListView(insightName)
            savedInsights.checkInsightIsNotInListView(expectedCopiedInsightName)
        })
        it('can duplicate a dashboard and duplicate insights', () => {
            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(dashboardName)

            cy.get('[data-attr="dashboard-three-dots-options-menu"]').click()
            duplicateDashboardFromMenu(true)
            cy.get('[data-attr="top-bar-name"] .EditableField__display').should(
                'have.text',
                expectedCopiedDashboardName
            )

            cy.wait('@createDashboard').then(() => {
                cy.contains('h4', expectedCopiedInsightName).click()
                cy.get('[data-attr="save-to-dashboard-button"] .LemonBadge').should('have.text', '1')
            })

            savedInsights.checkInsightIsInListView(insightName)
            savedInsights.checkInsightIsInListView(expectedCopiedInsightName)
        })
    })
})

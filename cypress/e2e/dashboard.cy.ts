import { urls } from 'scenes/urls'
import { randomString } from '../support/random'
import { insight, savedInsights, dashboards, dashboard, duplicateDashboardFromMenu } from '../productAnalytics'

describe('Dashboard', () => {
    beforeEach(() => {
        cy.intercept('GET', /api\/projects\/\d+\/insights\/\?.*/).as('loadInsightList')
        cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')
        cy.intercept('POST', /\/api\/projects\/\d+\/dashboards/).as('createDashboard')

        cy.clickNavMenu('dashboards')
        cy.location('pathname').should('include', '/dashboard')
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Dashboards')
    })

    it('Adding new insight to dashboard works', () => {
        cy.get('[data-attr=menu-item-insight]').click() // Create a new insight
        cy.get('[data-attr="insight-save-button"]').click() // Save the insight
        cy.url().should('not.include', '/new') // wait for insight to complete and update URL
        cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
        cy.get('[data-attr="insight-name"] input').type('Test Insight Zeus')
        cy.get('[data-attr="insight-name"] [title="Save"]').click()
        cy.get('[data-attr="save-to-dashboard-button"]').click() // Open the Save to dashboard modal
        cy.get('[data-attr="dashboard-list-item"] button').contains('Add to dashboard').first().click({ force: true }) // Add the insight to a dashboard
        cy.wait('@patchInsight').then(() => {
            cy.get('[data-attr="dashboard-list-item"] button').first().contains('Added')
            cy.get('[data-attr="dashboard-list-item"] a').first().click({ force: true }) // Go to the dashboard
            cy.get('[data-attr="insight-name"]').should('contain', 'Test Insight Zeus') // Check if the insight is there
        })
    })

    it('Cannot see tags or description (non-FOSS feature)', () => {
        cy.get('h1').should('contain', 'Dashboards')
        cy.get('th').contains('Description').should('not.exist')
        cy.get('th').contains('Tags').should('not.exist')

        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('.InsightCard').should('exist')
        cy.get('.dashboard-description').should('not.exist')
        cy.get('[data-attr=dashboard-tags]').should('not.exist')
    })

    it('Pinned dashboards on menu', () => {
        cy.clickNavMenu('events') // to make sure the dashboards menu item is not the active one
        cy.get('[data-attr=menu-item-pinned-dashboards]').click()
        cy.get('[data-attr=sidebar-pinned-dashboards]').should('be.visible')
        cy.get('[data-attr=sidebar-pinned-dashboards] a').should('contain', 'App Analytics')
    })

    it('Share dashboard', () => {
        dashboards.createDashboardFromDefaultTemplate('to be shared')

        cy.get('.InsightCard').should('exist')

        cy.get('[data-attr=dashboard-share-button]').click()
        cy.get('[data-attr=sharing-switch]').click({ force: true })

        cy.contains('Embed dashboard').should('be.visible')
        cy.get('[data-attr=copy-code-button]').click()
        cy.window().its('navigator.clipboard').invoke('readText').should('contain', '<iframe')
        cy.window().its('navigator.clipboard').invoke('readText').should('contain', '/embedded/')

        cy.contains('Copy share link').should('be.visible')
        cy.get('[data-attr=sharing-link-button]').click()
        cy.window().its('navigator.clipboard').invoke('readText').should('contain', '/shared/')
    })

    it('Create an empty dashboard', () => {
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr=dashboard-name-input]').clear().type('New Dashboard')
        cy.get('[data-attr="dashboard-submit-and-go"]').contains('Create and go to dashboard').click()

        cy.contains('New Dashboard').should('exist')
        cy.get('.EmptyDashboard').should('exist')

        // Check that dashboard is not pinned by default
        cy.get('.page-buttons [data-attr="dashboard-three-dots-options-menu"]').click()
        cy.get('button').contains('Pin dashboard').should('exist')
    })

    it('Create dashboard from a template', () => {
        const TEST_DASHBOARD_NAME = 'XDefault'

        dashboards.createDashboardFromDefaultTemplate(TEST_DASHBOARD_NAME)

        cy.get('.InsightCard').its('length').should('be.gte', 2)
        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Dashboards')
        cy.get('[data-attr=breadcrumb-3]').should('have.text', TEST_DASHBOARD_NAME)
    })

    it('Click on a dashboard item dropdown and view graph', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('a').contains('View').click()
        cy.location('pathname').should('include', '/insights')
    })

    it('Rename dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Rename').click()

        cy.get('[data-attr=modal-prompt]').clear().type('Test Name')
        cy.contains('OK').click()
        cy.contains('Test Name').should('exist')
    })

    it('Color dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Set color').click()
        cy.get('button').contains('Green').click()
        cy.get('.InsightCard .CardMeta__ribbon').should('have.class', 'green')
    })

    it('Duplicate dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Duplicate').click()
        cy.get('[data-attr=success-toast]').contains('Insight duplicated').should('exist')
    })

    it('Move dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Move to').click()
        cy.get('button').contains('App Analytics').click()
        cy.get('[data-attr=success-toast]').contains('Insight moved').should('exist')
    })

    it('Opens dashboard item in insights', () => {
        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('.InsightCard [data-attr=insight-card-title]').first().click()
        cy.location('pathname').should('include', '/insights')
        cy.get('[data-attr=funnel-bar-graph]', { timeout: 30000 }).should('exist')
    })

    it('Add insight from empty dashboard', () => {
        const dashboardName = randomString('dashboard-')
        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(randomString('insight-'))

        cy.wait(200)
        cy.get('.page-title').contains(dashboardName).should('exist')
    })

    describe('duplicating dashboards', () => {
        let dashboardName, insightName, expectedCopiedDashboardName, expectedCopiedInsightName

        beforeEach(() => {
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
                cy.get('h1.page-title').should('have.text', expectedCopiedDashboardName)

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
                cy.get('h1.page-title').should('have.text', expectedCopiedDashboardName)

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
                cy.get('h1.page-title').should('have.text', expectedCopiedDashboardName)

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
                cy.get('h1.page-title').should('have.text', expectedCopiedDashboardName)

                cy.wait('@createDashboard').then(() => {
                    cy.contains('h4', expectedCopiedInsightName).click()
                    cy.get('[data-attr="save-to-dashboard-button"] .LemonBadge').should('have.text', '1')
                })

                savedInsights.checkInsightIsInListView(insightName)
                savedInsights.checkInsightIsInListView(expectedCopiedInsightName)
            })
        })
    })

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

        it('can delete dashboard and delete the insights', () => {
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
                    cy.get('.row-name a').click()
                })

                insight.addInsightToDashboard(dashboardName)

                cy.get('[data-attr="dashboard-three-dots-options-menu"]').click()
                cy.get('button').contains('Delete dashboard').click()
                cy.contains('span.LemonCheckbox', "Delete this dashboard's insights").click()
                cy.get('[data-attr="dashboard-delete-submit"]').click()

                savedInsights.checkInsightIsInListView(insightToKeepName)
                savedInsights.checkInsightIsNotInListView(insightName)
            })
        })
    })
})

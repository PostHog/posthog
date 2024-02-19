import { randomString } from '../support/random'
import { insight, dashboards, dashboard } from '../productAnalytics'

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
        cy.get('[data-attr=breadcrumb-organization]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-project]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-Dashboards]').should('have.text', 'Dashboards')
    })

    // FIXME: this test works in real, but not in cypress
    it.skip('Adding new insight to dashboard works', () => {
        const dashboardName = randomString('to add an insight to')
        const insightName = randomString('insight to add to dashboard')

        // create and visit a dashboard to get it into turbomode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)

        insight.create(insightName)

        insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

        cy.get('.CardMeta h4').should('have.text', insightName)
    })

    it('Adding new insight to dashboard does not clear filters', () => {
        const dashboardName = randomString('to add an insight to')
        const firstInsight = randomString('insight to add to dashboard')
        const secondInsight = randomString('another insight to add to dashboard')

        // create and visit a dashboard to get it into turbomode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(firstInsight)

        dashboard.addAnyFilter()

        dashboard.addInsightToEmptyDashboard(secondInsight)

        cy.get('.PropertyFilterButton').should('have.length', 1)

        cy.get('.CardMeta h4').should('contain.text', firstInsight)
        cy.get('.CardMeta h4').should('contain.text', secondInsight)
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
        cy.get('[data-attr=menu-item-pinned-dashboards-dropdown]').click()
        cy.get('.Popover').should('be.visible')
        cy.get('.Popover a').should('contain', 'App Analytics')
    })

    it('Create an empty dashboard', () => {
        const dashboardName = 'New Dashboard 2'

        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr="create-dashboard-blank"]').click()
        cy.get('[data-attr="top-bar-name"]').should('exist')
        cy.get('[data-attr="top-bar-name"] button').click()
        cy.get('[data-attr="top-bar-name"] input').clear().type(dashboardName).blur()

        cy.contains(dashboardName).should('exist')
        cy.get('.EmptyDashboard').should('exist')

        // Check that dashboard is not pinned by default
        cy.get('.TopBar3000 [data-attr="dashboard-three-dots-options-menu"]').click()
        cy.get('button').contains('Pin dashboard').should('exist')
    })

    it('Create dashboard from a template', () => {
        const TEST_DASHBOARD_NAME = 'XDefault'

        dashboards.createDashboardFromDefaultTemplate(TEST_DASHBOARD_NAME)

        cy.get('.InsightCard').its('length').should('be.gte', 2)
        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-organization]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-project]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-Dashboards]').should('have.text', 'Dashboards')
        cy.get('[data-attr^="breadcrumb-Dashboard:"]').should('have.text', TEST_DASHBOARD_NAME + 'UnnamedCancelSave')
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
        cy.intercept('PATCH', /api\/projects\/\d+\/dashboards\/\d+\/move_tile.*/).as('moveTile')

        const sourceDashboard = randomString('source-dashboard')
        const targetDashboard = randomString('target-dashboard')
        const insightToMove = randomString('insight-to-move')
        dashboards.createAndGoToEmptyDashboard(sourceDashboard)
        const insightToLeave = randomString('insight-to-leave')
        dashboard.addInsightToEmptyDashboard(insightToLeave)
        dashboard.addInsightToEmptyDashboard(insightToMove)

        cy.wait(200)

        // create the target dashboard and get it cached by turbo-mode
        cy.clickNavMenu('dashboards')
        dashboards.createAndGoToEmptyDashboard(targetDashboard)

        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(sourceDashboard)

        cy.contains('.InsightCard ', insightToMove).within(() => {
            cy.get('[data-attr=more-button]').first().click({ force: true })
        })

        cy.get('button').contains('Move to').click()
        cy.get('button').contains(targetDashboard).click()

        cy.wait('@moveTile').then(() => {
            cy.get('.CardMeta h4').should('have.text', insightToLeave)

            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(targetDashboard)
            cy.get('.CardMeta h4').should('have.text', insightToMove)
        })
    })

    it('Opens dashboard item in insights', () => {
        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('.InsightCard [data-attr=insight-card-title]').first().click()
        cy.location('pathname').should('include', '/insights')
        cy.get('[data-attr=funnel-bar-horizontal]', { timeout: 30000 }).should('exist')
    })

    it('Add insight from empty dashboard', () => {
        const dashboardName = randomString('dashboard-')
        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(randomString('insight-'))

        cy.wait(200)
        cy.get('[data-attr="top-bar-name"] .EditableField__display').contains(dashboardName).should('exist')
    })
})

import { randomString } from '../support/random'
import { insight, dashboards, dashboard } from '../productAnalytics'
import { urls } from 'scenes/urls'

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

    it('Adding new insight to dashboard works', () => {
        const dashboardName = randomString('Dashboard with matching filter')
        const insightName = randomString('insight to add to dashboard')

        // Create and visit a dashboard to get it into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)

        insight.create(insightName)

        insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

        cy.get('.CardMeta h4').should('have.text', insightName)

        dashboard.addPropertyFilter()
        cy.get('main').contains('There are no matching events for this query').should('not.exist')

        cy.clickNavMenu('dashboards')
        const dashboardNonMatching = randomString('Dashboard with non-matching filter')
        dashboards.createAndGoToEmptyDashboard(dashboardNonMatching)

        insight.visitInsight(insightName)
        insight.addInsightToDashboard(dashboardNonMatching, { visitAfterAdding: true })

        dashboard.addPropertyFilter('Browser', 'Hogbrowser')
        cy.get('main').contains('There are no matching events for this query').should('exist')

        // Go back and forth to make sure the filters are correctly applied
        for (let i = 0; i < 3; i++) {
            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(dashboardName)
            cy.get('.CardMeta h4').should('have.text', insightName)
            cy.get('h4').contains('Refreshing').should('not.exist')
            cy.get('main').contains('There are no matching events for this query').should('not.exist')

            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(dashboardNonMatching)
            cy.get('.CardMeta h4').should('have.text', insightName)
            cy.get('h4').contains('Refreshing').should('not.exist')
            cy.get('main').contains('There are no matching events for this query').should('exist')
        }
    })

    it('Dashboard filter updates are correctly isolated for one insight on multiple dashboards', () => {
        const dashboardAName = randomString('Dashboard with insight A')
        const dashboardBName = randomString('Dashboard with insight B')
        const insightName = randomString('insight to add to dashboard')

        // Create and visit two dashboards to get them into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardAName)
        cy.clickNavMenu('dashboards')
        dashboards.createAndGoToEmptyDashboard(dashboardBName)

        insight.create(insightName)

        // Add that one insight to both dashboards
        insight.addInsightToDashboard(dashboardAName, { visitAfterAdding: false })
        cy.get('[aria-label="close"]').click()
        insight.addInsightToDashboard(dashboardBName, { visitAfterAdding: false })
        cy.get('[aria-label="close"]').click()

        // Let's get dashboard A mounted
        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(dashboardAName)
        cy.get('[data-attr=date-filter]').contains('No date range override')
        cy.get('.InsightCard h5').should('have.length', 1).contains('Last 7 days')
        // Now let's see dashboard B
        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(dashboardBName)
        cy.get('[data-attr=date-filter]').contains('No date range override')
        cy.get('.InsightCard h5').should('have.length', 1).contains('Last 7 days')
        // Override the time range on dashboard B
        cy.get('button').contains('Edit filters').click()
        cy.get('[data-attr=date-filter]').contains('No date range override').click()
        cy.get('div').contains('Yesterday').should('exist').click()
        cy.get('[data-attr=date-filter]').contains('Yesterday')
        cy.get('button').contains('Apply and save dashboard').click()
        cy.get('.InsightCard h5').should('have.length', 1).contains('Yesterday')
        // Cool, now back to A and make sure the insight is still using the original range there, not the one from B
        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(dashboardAName)
        cy.get('[data-attr=date-filter]').contains('No date range override')
        cy.get('.InsightCard h5').should('have.length', 1).contains('Last 7 days') // This must not be "Yesterday"!
    })

    it('Adding new insight to dashboard does not clear filters', () => {
        const dashboardName = randomString('to add an insight to')
        const firstInsight = randomString('insight to add to dashboard')
        const secondInsight = randomString('another insight to add to dashboard')

        // Create and visit a dashboard to get it into turbo mode cache
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

    const assertVariablesConfigurationScreenIsShown = (): void => {
        cy.get('[data-attr="new-dashboard-chooser"]').contains('Unique variable name').should('exist')
    }

    it('Allow reselecting a dashboard after pressing back', () => {
        cy.intercept('GET', /\/api\/projects\/\d+\/dashboard_templates/, (req) => {
            req.reply((response) => {
                response.body.results[0].variables = [
                    {
                        id: 'id',
                        name: 'Unique variable name',
                        type: 'event',
                        default: {},
                        required: true,
                        description: 'description',
                    },
                ]
                return response
            })
        })

        // Request templates again.
        cy.clickNavMenu('dashboards')

        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr="create-dashboard-from-template"]').click()
        assertVariablesConfigurationScreenIsShown()

        cy.contains('.LemonButton', 'Back').click()

        cy.get('[data-attr="create-dashboard-from-template"]').click()
        assertVariablesConfigurationScreenIsShown()
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

        cy.get('[data-attr=insight-name]').clear().type('Test Name')
        cy.contains('Submit').click()
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
        cy.get('[data-attr=funnel-bar-vertical]', { timeout: 30000 }).should('exist')
    })

    it('Add insight from empty dashboard', () => {
        const dashboardName = randomString('dashboard-')
        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(randomString('insight-'))

        cy.wait(200)
        cy.get('[data-attr="top-bar-name"] .EditableField__display').contains(dashboardName).should('exist')
    })
})

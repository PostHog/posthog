import { randomString } from '../support/random'
import { urls } from 'scenes/urls'

function createDashboardFromTemplate(dashboardName) {
    cy.get('[data-attr="new-dashboard"]').click()
    cy.get('[data-attr=dashboard-name-input]').clear().type(dashboardName)
    cy.get('[data-attr=copy-from-template]').click()
    cy.get('[data-attr=dashboard-select-default-app]').click()

    cy.get('[data-attr=dashboard-submit-and-go]').click()

    cy.contains(dashboardName).should('exist')
}

function visitDashboardsPage() {
    cy.clickNavMenu('dashboards')
    cy.location('pathname').should('include', '/dashboard')
}

describe('Dashboard', () => {
    beforeEach(() => {
        visitDashboardsPage()
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Dashboards')
    })

    describe.only('adding and removing insights', () => {
        it('Adding new insight to dashboard works', () => {
            cy.intercept(/api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')

            const insightName = randomString('insight-')

            cy.get('[data-attr=menu-item-insight]').click() // Create a new insight
            cy.get('[data-attr="insight-save-button"]').click() // Save the insight
            cy.url().should('not.include', '/new') // wait for insight to complete and update URL
            cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
            cy.get('[data-attr="insight-name"] input').type(insightName)
            cy.get('[data-attr="insight-name"] [title="Save"]').click()
            cy.get('[data-attr="save-to-dashboard-button"]').click() // Open the Save to dashboard modal
            cy.get('[data-attr="dashboard-list-item"] button')
                .contains('Add to dashboard')
                .first()
                .click({ force: true }) // Add the insight to a dashboard
            cy.wait('@patchInsight').then(() => {
                cy.get('[data-attr="dashboard-list-item"] button').first().contains('Added')
                cy.get('[data-attr="dashboard-list-item"] a').first().click({ force: true }) // Go to the dashboard
                cy.get('[data-attr="insight-name"]').should('contain', insightName) // Check if the insight is there
            })
        })

        it('Add insight to a dashboard and then remove it from the insight view', () => {
            cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')
            cy.intercept('POST', /api\/projects\/\d+\/insights\//).as('postInsight')
            cy.intercept('GET', /api\/projects\/\d+\/insights\/\?short_id=.*/).as('loadInsightView')

            const insightName = randomString('insight-')
            const dashboardName = randomString('Watermelon-')

            cy.get('[data-attr="new-dashboard"]').click()
            cy.get('[data-attr=dashboard-name-input]').clear().type(dashboardName)
            cy.get('button').contains('Create').click()

            cy.get('[data-attr=dashboard-add-graph-header]').contains('Add insight').click()
            cy.get('[data-attr=toast-close-button]').click()
            cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
            cy.get('[data-attr="insight-name"] input').type(insightName)

            cy.get('[data-attr=insight-save-button]').contains('Save & add to dashboard').click()
            cy.wait('@postInsight').then(() => {
                cy.url().should('include', '/dashboard/')
                cy.get('.page-title').contains(dashboardName).should('exist')
                cy.contains('.InsightMeta h4', insightName).should('exist').click()
                cy.wait('@loadInsightView').then(() => {
                    cy.url().should('include', '/insights/')
                    cy.contains('button', 'Add to dashboard').should('exist').click()
                    cy.contains('[data-attr="dashboard-list-item"]', dashboardName).within(() => {
                        // turbo mode has updated the insight if the button says "Added"
                        cy.get('button').should('have.text', 'Added').click({ force: true })
                    })
                })
            })

            cy.wait('@patchInsight').then(() => {
                // having removed it, check it isn't on the dashboard
                cy.contains('[data-attr="dashboard-list-item"] a', dashboardName).click({ force: true })
                cy.contains('Dashboard empty').should('exist')
            })
        })

        it.only('Add insight to a dashboard and then remove it from the dashboard view', () => {
            cy.intercept('PATCH', /api\/projects\/\d+\/dashboards\/\d+\/.*/).as('patchDashboard')
            cy.intercept('POST', /api\/projects\/\d+\/insights\//).as('postInsight')
            cy.intercept('GET', /api\/projects\/\d+\/insights\/\?short_id=.*/).as('loadInsightView')

            const insightName = randomString('insight-')
            const dashboardName = randomString('Watermelon-')

            cy.get('[data-attr="new-dashboard"]').click()
            cy.get('[data-attr=dashboard-name-input]').clear().type(dashboardName)
            cy.get('button').contains('Create').click()

            cy.get('[data-attr=dashboard-add-graph-header]').contains('Add insight').click()
            cy.get('[data-attr=toast-close-button]').click()
            cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
            cy.get('[data-attr="insight-name"] input').type(insightName)

            cy.get('[data-attr=insight-save-button]').contains('Save & add to dashboard').click()
            cy.wait('@postInsight').then(() => {
                cy.url().should('include', '/dashboard/')
                cy.get('.page-title').contains(dashboardName).should('exist')
                cy.contains('.InsightMeta h4', insightName).should('exist').click()
                cy.wait('@loadInsightView').then(() => {
                    cy.url().should('include', 'insights')
                    cy.contains('button', 'Add to dashboard').should('exist').click()
                    cy.contains('[data-attr="dashboard-list-item"]', dashboardName).within(() => {
                        // turbo mode has updated the insight if the button says "Added"
                        cy.get('button').should('have.text', 'Added')
                        cy.get('a').click({ force: true })
                    })
                })
            })

            cy.contains('.InsightMeta', insightName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            cy.contains('button', 'Remove from dashboard').click()
            cy.wait('@patchDashboard').then(() => {
                cy.contains('Dashboard empty').should('be.visible')
            })

            // confirm the insight no longer has the dashboard listed in its "Add to dashboard" button
            cy.visit(urls.savedInsights())
            cy.contains('.saved-insights a', insightName).should('exist').click()
            cy.url().should('include', 'insights')
            cy.contains('button', 'Add to dashboard').should('exist').click()
            cy.contains('[data-attr="dashboard-list-item"]', dashboardName).within(() => {
                cy.get('button').should('have.text', 'Add to dashboard')
            })
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
        createDashboardFromTemplate('to be shared')

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
        cy.get('button').contains('Create').click()

        cy.contains('New Dashboard').should('exist')
        cy.get('.EmptyDashboard').should('exist')

        // Check that dashboard is not pinned by default
        cy.get('.page-buttons [data-attr="dashboard-three-dots-options-menu"]').click()
        cy.get('button').contains('Pin dashboard').should('exist')
    })

    it('Create dashboard from a template', () => {
        const TEST_DASHBOARD_NAME = 'XDefault'

        createDashboardFromTemplate(TEST_DASHBOARD_NAME)

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
        cy.get('.InsightCard .InsightMeta__ribbon').should('have.class', 'green')
    })

    it('Duplicate dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Duplicate').click()
        cy.get('[data-attr=success-toast]').contains('Insight duplicated').should('exist')
    })

    it('Move dashboard item', () => {
        // load the dashboardLogic for the target so we're testing turbo mode
        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        visitDashboardsPage()
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()

        // create an insight to move
        cy.get('[data-attr="dashboard-add-graph-header"]').click()
        const insightName = randomString('insight')
        cy.get('[data-attr="insight-name"]').should('have.text', 'Pageview count')
        cy.get('[data-attr="edit-prop-name"]').click()
        cy.get('[data-attr="insight-name"] input').type(insightName)
        cy.get('[data-attr="insight-save-button"]').click()

        cy.contains('.InsightCard--highlighted', insightName).within(($insightCard) => {
            cy.get('[data-attr="more-button"]').click()
        })

        cy.intercept(/api\/projects\/\d+\/dashboards\/\d+\/move_tile/).as('moveTile')

        cy.get('[data-attr="insight-move-to-dashboard"]').click()
        cy.contains('button', 'App Analytics').click()

        cy.wait('@moveTile').then(({ request }) => {
            cy.get('[data-attr=success-toast]').contains('Insight moved').should('exist')

            visitDashboardsPage()
            cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
            cy.get('.InsightCard h4').contains(insightName).should('exist')
        })

        // confirm that the insight's dashboard list was updated in turbo mode
        cy.get('.InsightCard h4').contains(insightName).click()
        cy.contains('button', 'Add to dashboard').click()
        cy.contains('[data-attr="dashboard-list-item"]', 'App Analytics').within(() => {
            cy.get('button').should('have.text', 'Added')
        })
        cy.contains('[data-attr="dashboard-list-item"]', 'Web Analytics').within(() => {
            cy.get('button').should('have.text', 'Add to dashboard')
        })
    })

    it('Opens dashboard item in insights', () => {
        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('.InsightCard [data-attr=insight-card-title]').first().click()
        cy.location('pathname').should('include', '/insights')
        cy.get('[data-attr=funnel-bar-graph]', { timeout: 30000 }).should('exist')
    })
})

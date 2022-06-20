function createDashboardFromTemplate(dashboardName) {
    cy.get('[data-attr="new-dashboard"]').click()
    cy.get('[data-attr=dashboard-name-input]').clear().type(dashboardName)
    cy.get('[data-attr=copy-from-template]').click()
    cy.get('[data-attr=dashboard-select-default-app]').click()

    cy.get('button').contains('Create').click()

    cy.contains(dashboardName).should('exist')
}

describe('Dashboard', () => {
    beforeEach(() => {
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
        cy.wait(100)
        cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
        cy.focused().clear().type('Test Insight Zeus')
        cy.get('button').contains('Save').click() // Save the new name
        cy.get('[data-attr="save-to-dashboard-button"]').click() // Open the Save to dashboard modal
        cy.get('.modal-row button').contains('Add to dashboard').first().click({ force: true }) // Add the insight to a dashboard
        cy.get('.modal-row button').first().contains('Added')
        cy.get('.modal-row a').first().click({ force: true }) // Go to the dashboard
        cy.get('[data-attr="insight-name"]').should('contain', 'Test Insight Zeus') // Check if the insight is there
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
        cy.get('[data-attr=sidebar-pinned-dashboards] div').should('contain', 'App Analytics')
    })

    it.only('Share dashboard', (done) => {
        createDashboardFromTemplate('to be shared')

        cy.get('.InsightCard').should('exist')

        cy.get('[data-attr=dashboard-share-button]').click()
        cy.get('[data-attr=share-dashboard-switch]').click({ force: true })
        cy.contains('Copy shared dashboard link').should('be.visible')
        cy.get('[data-attr=share-dashboard-link-button]').click()
        cy.window().then((win) => {
            win.navigator.clipboard.readText().then((linkFromClipboard) => {
                cy.visit(linkFromClipboard)
                cy.get('[data-attr=dashboard-item-title]').should('contain', 'to be shared')
                done()
            })
        })
    })

    it('Create an empty dashboard', () => {
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr=dashboard-name-input]').clear().type('New Dashboard')
        cy.get('button').contains('Create').click()

        cy.contains('New Dashboard').should('exist')
        cy.get('.empty-state').should('exist')

        // Check that dashboard is not pinned by default
        cy.get('.page-buttons [data-attr="more-button"]').click()
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
        cy.get('button').contains('View').click()
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
        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr=dashboard-name-input]').clear().type('Watermelon')
        cy.get('button').contains('Create').click()

        cy.get('[data-attr=dashboard-add-graph-header]').contains('Add insight').click()
        cy.get('[data-attr=toast-close-button]').click()
        cy.get('[data-attr=insight-save-button]').contains('Save & add to dashboard').click()

        cy.wait(200)
        cy.get('.page-title').contains('Watermelon').should('exist')
    })
})

import { dashboards } from '../productAnalytics'

describe('Shared dashboard', () => {
    beforeEach(() => {
        cy.intercept('GET', /api\/projects\/\d+\/insights\/\?.*/).as('loadInsightList')
        cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')
        cy.intercept('POST', /\/api\/projects\/\d+\/dashboards/).as('createDashboard')
        cy.useSubscriptionStatus('unsubscribed')

        cy.clickNavMenu('dashboards')
    })

    it('Dashboard sharing can be enabled', () => {
        dashboards.createDashboardFromDefaultTemplate('to be shared')

        cy.get('.InsightCard').should('exist')

        cy.get('[data-attr=dashboard-share-button]').click()
        cy.get('[data-attr=sharing-switch]').click({ force: true })

        cy.contains('Embed dashboard').should('be.visible')
        cy.get('[data-attr=copy-code-button]').click()
        cy.window()
            .its('navigator.clipboard')
            .then((c) => c.readText())
            .should('contain', '<iframe')
        cy.window()
            .its('navigator.clipboard')
            .then((c) => c.readText())
            .should('contain', '/embedded/')

        cy.contains('Copy public link').should('be.visible')
        cy.get('[data-attr=sharing-link-button]').click()
        cy.window()
            .its('navigator.clipboard')
            .then((c) => c.readText())
            .should('contain', '/shared/')
    })

    it('Insights load when cache is empty', () => {
        cy.get('h1').should('contain', 'Dashboards')

        dashboards.createDashboardFromDefaultTemplate('Foobar 3001')

        cy.get('[data-attr=dashboard-share-button]').click()
        cy.get('[data-attr=sharing-switch]').click({ force: true })

        cy.contains('Copy public link').should('be.visible')
        cy.get('[data-attr=sharing-link-button]').click()
        cy.window()
            .its('navigator.clipboard')
            .then((clipboard) => {
                cy.wrap(clipboard.readText()).as('clipboardText')
            })

        cy.task('resetInsightCache')

        cy.window().then(async (win) => {
            const text = await win.navigator.clipboard.readText()
            cy.visit(text)
        })

        cy.get('.InsightCard').should('have.length', 6)
        // Make sure no element with text "There are no matching events for this query" exists
        cy.get('.insight-empty-state').should('not.exist')
    })
})

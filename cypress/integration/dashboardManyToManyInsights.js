import { uuid } from 'lib/utils'
import decideResponse from 'cypress/fixtures/api/decide'

let dashboardOne
let dashboardTwo
let insight

function createADashboard(name) {
    cy.clickNavMenu('dashboards')
    cy.location('pathname').should('include', '/dashboard')

    cy.get('[data-attr="new-dashboard"]').click()
    cy.get('[data-attr=dashboard-name-input]').clear().type(name)
    cy.get('button').contains('Create').click()
}

function addInsightToDashboard(name) {
    cy.clickNavMenu('savedinsights')
    cy.location('pathname').should('include', '/insights')

    cy.get('td a').contains(insight).click()
    cy.get('button').contains('Add to dashboard').click()

    cy.get('[data-attr="dashboard-searchfield"]').type(name)

    cy.get('.add-to-dashboard-modal .modal-row').contains(name).parents('.modal-row').find('button').click()
    cy.get('.add-to-dashboard-modal .modal-row')
        .contains(name)
        .parents('.modal-row')
        .find('button')
        .should('have.text', 'Added')

    cy.get('.add-to-dashboard-modal .modal-row').contains(name).parents('.modal-row').find('a').click()
}

describe('Dashboard', () => {
    before(() => {
        cy.intercept('POST', '**/decide/*', (req) => req.reply(decideResponse(['multi-dashboard-insights']))).as(
            'setFlags'
        )
    })

    beforeEach(() => {
        dashboardOne = `dashboard one ${uuid()}`
        dashboardTwo = `dashboard two ${uuid()}`
        insight = `To add to two dashboards ${uuid()}`

        cy.clickNavMenu('dashboards')
        cy.location('pathname').should('include', '/dashboard')
    })

    it.only('Adding insight to two dashboards works', () => {
        // create two dashboards
        createADashboard(dashboardOne)
        createADashboard(dashboardTwo)

        // create an insight
        cy.get('[data-attr=menu-item-insight]').click() // Create a new insight
        cy.get('[data-attr="insight-save-button"]').click() // Save the insight
        cy.wait(100)
        cy.get('[data-attr="edit-prop-name"]').click({ force: true }) // Rename insight, out of view, must force
        cy.focused().clear().type(insight)
        cy.get('button').contains('Save').click() // Save the new name

        // add the insight to one dashboard
        addInsightToDashboard(dashboardOne)

        // view it on one dashboard
        cy.get('h1.page-title').should('have.text', dashboardOne)
        cy.get('.InsightCard .InsightMeta h4').should('have.text', insight)

        // dates are inside canvas and cypress can't test that the data is correct if we change the date filter
        // TODO test that changing date range on dashboard consistently changes graph

        // add it to a second dashboard
        addInsightToDashboard(dashboardTwo)

        // view it on second dashboards
        cy.get('.page-title').should('have.text', dashboardTwo)
        cy.get('.InsightCard .InsightMeta h4').should('have.text', insight)

        // dates are inside canvas and cypress can't test that the data is correct if we change the date filter
        // TODO test that changing date range on dashboard consistently changes graph

        // load the insight and check it shows it is connected to two dashboards
        cy.get('.InsightCard .InsightMeta h4').click()
        cy.get('[data-attr="save-to-dashboard-button"]').should('have.text', '2Add to dashboard')
    })
})

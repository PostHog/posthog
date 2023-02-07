import { urls } from 'scenes/urls'

describe('Licenses', () => {
    it('Licenses loaded for billing v1', () => {
        cy.intercept('GET', '/api/billing-v2**', { statusCode: 500 }).as('billingServerFailure')
        cy.visit(urls.savedInsights())
        cy.wait('@billingServerFailure')
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-licenses]').click()
        cy.get('[data-attr=breadcrumb-0]').should('contain', Cypress.config().baseUrl.replace('http://', '')) // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-1]').should('have.text', 'Licenses') // Breadcrumbs work
        cy.get('h1').should('contain', 'Licenses')
        cy.title().should('equal', 'Licenses • PostHog') // Page title works
    })

    it('License page not visible on billing v2', () => {
        cy.intercept('GET', '/api/billing-v2**', { statusCode: 200 }).as('billingServerSuccess')
        cy.visit(urls.savedInsights())
        cy.wait('@billingServerSuccess')
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-licenses]').should('not.exist')
    })
})

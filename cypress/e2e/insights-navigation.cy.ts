import { urls } from 'scenes/urls'

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    describe('navigation', () => {
        it('can open event explorer as an insight', () => {
            cy.clickNavMenu('activity')
            cy.get('[data-attr="open-json-editor-button"]').click()
            cy.get('[data-attr="insight-json-tab"]').should('exist')
        })

        it('does not show the json tab usually', () => {
            cy.clickNavMenu('savedinsights')
            cy.get('[data-attr="insight-json-tab"]').should('not.exist')
        })
    })
})

import { insight, savedInsights } from '../productAnalytics'

describe('Notebooks', () => {
    beforeEach(() => {
        cy.clickNavMenu('notebooks')
        cy.location('pathname').should('include', '/notebooks')
    })

    it(`Can add a HogQL insight`, () => {
        savedInsights.createNewInsightOfType('SQL')
        insight.editName('SQL Insight')
        insight.save()
        cy.get('[data-attr="notebooks-add-button"]').click()
        cy.get('[data-attr="notebooks-select-button-create"]').click()
        cy.get('.ErrorBoundary').should('not.exist')
        // Detect if table settings are present. They shouldn't appear in the block, but rather on side.
        cy.get('[data-attr="notebook-node-query"]').get('[data-attr="export-button"]').should('not.exist')
    })
    ;['TRENDS', 'FUNNELS', 'RETENTION', 'PATHS', 'STICKINESS', 'LIFECYCLE'].forEach((insightType) => {
        it(`Can add a ${insightType} insight`, () => {
            savedInsights.createNewInsightOfType(insightType)
            insight.editName(`${insightType} Insight`)
            insight.save()
            cy.get('[data-attr="notebooks-add-button"]').click()
            cy.get('[data-attr="notebooks-select-button-create"]').click()
            cy.get('.ErrorBoundary').should('not.exist')
        })
    })
})

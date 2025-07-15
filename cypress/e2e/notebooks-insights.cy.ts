import { insight, savedInsights } from '../productAnalytics'

describe('Notebooks', () => {
    beforeEach(() => {
        cy.clickNavMenu('notebooks')
        cy.location('pathname').should('include', '/notebooks')
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

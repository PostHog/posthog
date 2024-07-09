import { urls } from 'scenes/urls'

import { createInsight, savedInsights } from '../productAnalytics'
import { randomString } from '../support/random'

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    describe('duplicating insights', () => {
        let insightName
        beforeEach(() => {
            cy.visit(urls.savedInsights()) // make sure turbo mode has cached this page
            insightName = randomString('insight-name-')
            createInsight(insightName)
        })
        it('can duplicate insights from the insights list view', () => {
            cy.visit(urls.savedInsights())
            cy.contains('.saved-insights table tr', insightName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            cy.get('[data-attr="duplicate-insight-from-list-view"]').click()
            cy.contains('.saved-insights table tr', `${insightName} (copy)`).should('exist')
        })

        it('can duplicate insights from the insights card view', () => {
            cy.visit(urls.savedInsights())
            cy.contains('.saved-insights .LemonSegmentedButton', 'Cards').click()
            cy.contains('.CardMeta', insightName).within(() => {
                cy.get('[data-attr="more-button"]').click()
            })
            cy.get('[data-attr="duplicate-insight-from-card-list-view"]').click()
            cy.contains('.CardMeta', `${insightName} (copy)`).should('exist')
        })

        it('can duplicate from insight view', () => {
            cy.get('.TopBar3000 [data-attr="more-button"]').click()
            cy.get('[data-attr="duplicate-insight-from-insight-view"]').click()
            cy.get('[data-attr="top-bar-name"] .EditableField__display').should('contain', `${insightName} (copy)`)

            savedInsights.checkInsightIsInListView(`${insightName} (copy)`)
        })

        it('can save insight as a copy', () => {
            cy.get('[data-attr="insight-edit-button"]').click()

            cy.get('[data-attr="insight-save-dropdown"]').click()
            cy.get('[data-attr="insight-save-as-new-insight"]').click()
            cy.get('button[type=submit]').click()
            cy.get('[data-attr="top-bar-name"] .EditableField__display').should('contain', `${insightName} (copy)`)

            savedInsights.checkInsightIsInListView(`${insightName} (copy)`)
        })
    })
})

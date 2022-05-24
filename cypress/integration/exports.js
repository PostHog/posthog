import { urls } from 'scenes/urls'

import { decideResponse } from '../fixtures/api/decide'

describe('Exporting Insights', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'export-dashboard-insights': true,
                })
            )
        )
        cy.visit(urls.savedInsights())
        cy.contains('Weekly active users (WAUs)').click()
        cy.wait(3000)
    })

    it('Export an Insight to png', () => {
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=export-button]').click()
        cy.get('[data-attr=export-button-png]').click()

        const expecteFileName = 'export-weekly-active-users-waus.png'
        // NOTE: As the API data is only mocked in cypress, the image will always have empty data...
        cy.task('compareToReferenceImage', {
            source: expecteFileName,
            reference: `../data/exports/${expecteFileName}`,
        })
    })
})

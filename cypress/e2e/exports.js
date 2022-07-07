import { urls } from 'scenes/urls'

import { decideResponse } from '../fixtures/api/decide'

// NOTE: As the API data is randomly generated, we are only really testing here that the overall output is correct
// The actual graph is not under test
describe('Exporting Insights', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'export-dashboard-insights': true,
                    ASYNC_EXPORT_CSV_FOR_LIVE_EVENTS: true,
                })
            )
        )
        cy.visit(urls.insightNew())
        // apply filter
        cy.get('[data-attr=insight-filters-add-filter-group]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=expand-list-event_properties]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        cy.get('[data-attr=prop-val] input').type('not-applicable')
        cy.get('[data-attr=prop-val] input').type('{enter}')

        // Save
        cy.get('[data-attr="insight-save-button"]').click()
    })

    it('Export an Insight to png', () => {
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=export-button]').first().click()
        cy.get('[data-attr=export-button-png]').click()

        const expecteFileName = 'export-pageview-count.png'
        cy.task('compareToReferenceImage', {
            source: expecteFileName,
            reference: `../data/exports/${expecteFileName}`,
            diffThreshold: 0.01,
        })
    })
})

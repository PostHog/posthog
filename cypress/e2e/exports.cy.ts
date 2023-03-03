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
                })
            )
        )
        cy.visit(urls.insightNew())
        // apply filter
        cy.get('[data-attr=insight-filters-add-filter-group]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        cy.get('[data-attr=prop-val] input').type('not-applicable')
        cy.get('[data-attr=prop-val] input').type('{enter}')

        // Save
        cy.get('[data-attr="insight-save-button"]').click()
    })

    it('Export an Insight to png', () => {
        cy.get('[data-attr="insight-edit-button"]').should('exist') // Export is only available in view mode
        cy.get('.page-buttons [data-attr=more-button]').click()
        cy.get('.Popover [data-attr=export-button]').click()
        cy.get('[data-attr=export-button-png]').click()

        // Ensure that no popovers are being shown
        cy.wait(500)
        cy.get('.Popover').should('not.exist')

        const expectedFileName = 'export-pageview-count.png'
        cy.task('compareToReferenceImage', {
            source: expectedFileName,
            reference: `../data/exports/${expectedFileName}`,
            diffThreshold: 0.01,
        })
    })
})

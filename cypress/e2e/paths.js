import { urls } from 'scenes/urls'

describe('Paths', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
        cy.get('[data-attr=insight-path-tab]').click()
    })

    it('Paths loaded', () => {
        cy.get('[data-attr=paths-viz]').should('exist')
    })

    it('Apply date filter', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=paths-viz]').should('exist')
    })

    it('can save paths', () => {
        cy.get('[data-attr="insight-edit-button"]').should('not.exist')
        cy.get('[data-attr="insight-save-button"]').click()
        cy.get('[data-attr="insight-edit-button"]').should('exist')
    })
})

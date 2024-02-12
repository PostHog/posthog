import { urls } from 'scenes/urls'

describe('Retention', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
        cy.get('[data-attr=insight-retention-tab]').click()
    })

    it('should apply filter and navigate to persons', () => {
        // NOTE: First wait for results to load, try and make the test more
        // stable. This is to try and avoid an issue where after selecting a
        // filter property, the results section would be blank
        cy.get('[data-attr=retention-table').should('exist')
        // tests for new property group filters
        // cy.get('[data-attr=insight-retention-add-filter-group]').click()
        // cy.get('[data-attr=property-select-toggle-0]').click()

        cy.get('[data-attr$=add-filter-group]').click()
        cy.get('[data-attr=property-select-toggle-0]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('is_demo')
        cy.get('[data-attr=taxonomic-tab-person_properties]').click()
        cy.get('[data-attr=prop-filter-person_properties-0]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()
        cy.get('[data-attr=retention-table').should('exist')

        // cy.get('.percentage-cell').last().click()

        // cy.get('[data-attr=retention-person-link]').its('length').should('eq', 1)
        // cy.get('[data-attr=retention-person-link]').contains('smith.nunez@gmail.com')

        // cy.get('[data-attr=retention-person-link]').click()

        // cy.url().should('include', '/person/')
        // cy.contains('smith.nunez@gmail.com').should('exist')
    })
})

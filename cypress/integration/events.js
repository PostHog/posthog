describe('Events', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
    })

    it('Events loaded', () => {
        cy.get('[data-attr=events-table').should('exist')
    })

    it('Click on an event', () => {
        cy.get('[data-attr=event-name-0').click()
        cy.get('[data-attr=event-details').should('exist')
    })

    it('All events route works', () => {
        cy.get('[data-attr=menu-item-all-events]').click()

        cy.get('[data-attr=events-table').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-EventsTable]').click()
        cy.contains('$current_url').click()
        cy.get('[data-attr=prop-val]').click()
        cy.contains(Cypress.config().baseUrl + '/demo/1/').click()

        cy.get('[data-attr=events-table').should('exist')
    })
})

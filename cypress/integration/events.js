describe('Events', () => {
    beforeEach(() => {
        cy.visit('/events')
    })

    it('Events loaded', () => {
        cy.get('[data-attr=events-table').should('exist')
    })

    it('Click on an event', () => {
        cy.get('[data-attr=events-table] .event-row:first-child td:first-child').click()
        cy.get('[data-attr=event-details').should('exist')
    })

    it('All events route works', () => {
        cy.get('[data-attr=menu-item-all-events]').click()

        cy.get('[data-attr=events-table').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-EventsTable]').click()
        cy.get('[data-attr=prop-filter-event-0]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()
        cy.get('[data-attr=events-table').should('exist')
    })

    it('Filter by event', () => {
        cy.get('[data-attr=event-filter-trigger]').click()
        cy.get('[data-attr=event-name-box]').click()
        cy.get('[data-attr=prop-val-0]').click()
        cy.get('[data-attr=events-table').should('exist')
    })
})

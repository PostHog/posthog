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
})

describe('Event Definitions', () => {
    beforeEach(() => {
        cy.visit('/data-management/events')
    })

    it('See recordings action', () => {
        cy.get('[data-attr=events-definition-table]').should('exist')
        cy.get('[data-attr=event-definitions-table-more-button-entered_free_trial]').first().click()
        cy.get('[data-attr=event-definitions-table-view-recordings]').should('exist')
        cy.get('[data-attr=event-definitions-table-view-recordings]').click()
        cy.url().should('contain', 'entered_free_trial')
    })
})

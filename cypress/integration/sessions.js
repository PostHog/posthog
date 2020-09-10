describe('Sessions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]', { timeout: 7000 }).click()
        cy.get('[data-attr=menu-item-sessions]', { timeout: 7000 }).click()
    })

    it('Sessions Table loaded', () => {
        cy.get('h1').should('contain', 'Sessions')
        cy.get('[data-attr=sessions-table]').should('exist')
    })
})

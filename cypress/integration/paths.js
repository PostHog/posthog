describe('Paths', () => {
    beforeEach(() => {
        cy.visit('/')
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
})

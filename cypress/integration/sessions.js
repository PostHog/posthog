describe('Sessions', () => {
    beforeEach(() => {
        cy.clickNavMenu('sessions')
    })

    it('Sessions Table loaded', () => {
        cy.get('h1').should('contain', 'Sessions')
        cy.get('[data-attr=sessions-table]').should('exist')
    })
})

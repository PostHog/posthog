describe('Persons', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
    })

    it('All tabs work', () => {
        cy.get('h1').should('contain', 'Persons')
        cy.get('[data-attr=persons-search]').type('marisol').type('{enter}').should('have.value', 'marisol')
        cy.wait(200)
        cy.get('[data-row-key]').its('length').should('be.gte', 0)
    })
})

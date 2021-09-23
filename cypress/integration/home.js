describe('Home', () => {
    beforeEach(() => {
        cy.visit('/home')
        cy.location('pathname').should('include', '/home')
    })

    it('Home loaded', () => {
        cy.get('h1').should('contain', 'Home')
    })
})

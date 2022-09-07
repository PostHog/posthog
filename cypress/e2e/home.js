describe('the home page', () => {
    it('has valid html markup', () => {
        cy.visit('/home')
        cy.get('.InsightCard').should('be.visible')
        cy.htmlvalidate()
    })
})

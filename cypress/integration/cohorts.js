describe('Cohorts', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]', { timeout: 7000 }).click()
        cy.get('[data-attr=menu-item-cohorts]', { timeout: 7000 }).click()
    })
    it('Cohorts loaded', () => {
        cy.get('h1').should('contain', 'Cohorts')
    })
})

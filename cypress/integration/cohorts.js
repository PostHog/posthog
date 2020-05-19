describe('Cohorts', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click()
    })
    it('Cohorts loaded', () => {
        cy.get('[data-attr=menu-item-cohorts]').click()

        cy.get('h1').should('contain', 'Cohorts')
    })
})

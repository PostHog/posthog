describe('Cohorts', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click()
        cy.get('[data-attr=menu-item-people-cohorts]').click()
    })
    it('Cohorts loaded', () => {
        cy.get('h1').should('contain', 'Cohorts')
    })
})

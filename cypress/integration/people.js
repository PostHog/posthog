describe('People', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click()
    })

    it('People loaded', () => {
        cy.get('h1').should('contain', 'Users')
    })

    it('All people route works', () => {
        cy.get('[data-attr=menu-item-cohorts]').click()
        cy.get('[data-attr=menu-item-all-people]').click()

        cy.get('h1').should('contain', 'Users')
    })
})

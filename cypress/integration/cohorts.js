describe('Cohorts', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click()
        cy.get('[data-attr=menu-item-cohorts]').click()
    })
    it('Cohorts loaded', () => {
        cy.get('h1').should('contain', 'Cohorts')
    })

    it('Go to new cohort from cohorts screen', () => {
        cy.get('[data-attr=create-cohort]').click()
        cy.get('span').should('contain', 'New cohort')
    })
})

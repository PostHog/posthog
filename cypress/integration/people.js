describe('People', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click()
    })

    it('People loaded', () => {
        cy.get('h1').should('contain', 'Users')
    })

    it('Go to new cohort from people screen', () => {
        cy.get('[data-attr=create-cohort]').click()
        cy.get('span').should('contain', 'New Cohort')
    })

    it('All people route works', () => {
        cy.get('[data-attr=menu-item-cohorts]').click()
        cy.get('[data-attr=menu-item-all-people]').click()

        cy.get('h1').should('contain', 'Users')
    })

    it('Retention route works', () => {
        cy.get('[data-attr=menu-item-retention]').click()

        cy.get('h1').should('contain', 'Retention')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=menu-item-retention]').click()
        cy.get('[data-attr=new-prop-filter-RetentionTable]').click()
        cy.get('[data-attr=prop-filter-person-0]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()
        cy.get('[data-attr=retention-table').should('exist')
    })
})

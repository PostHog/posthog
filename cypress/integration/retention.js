describe('Retention', () => {
    beforeEach(() => {
        cy.visit('/')
        cy.get('[data-attr=insight-retention-tab]').click()
    })

    it('Retention tab exists', () => {
        cy.get('[data-attr=retention-tab]').should('exist')
    })

    it('Apply 1 overall filter', () => {
        cy.get('[data-attr=new-prop-filter-insight-retention]').click()
        cy.get('[data-attr=prop-filter-person-0]').click()
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click()
        cy.get('[data-attr=retention-table').should('exist')
    })
})

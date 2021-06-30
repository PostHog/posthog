describe('Sessions', () => {
    beforeEach(() => {
        cy.clickNavMenu('sessions')
    })

    it('Sessions Table loaded', () => {
        cy.get('h1').should('contain', 'Sessions')
        cy.get('[data-attr=sessions-table]').should('exist')
    })

    it('Sessions Table highlights matches', () => {
        // Add pageview filter
        cy.get('[data-attr=sessions-filter-open]').click()
        cy.get('.ant-input').type('Pageview')
        cy.get('.ant-list-item').contains('Pageview').click()

        cy.get('[data-attr=sessions-apply-filters]').click()

        /* BLocked on writing any meaningful sessions tests until #4929 is fixed.  */
    })
})

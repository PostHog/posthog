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

    it('All tabs work', () => {
        cy.get('.form-control').type('has:email').type('{enter}').should('have.value', 'has:email')
        cy.wait(200)
        cy.get('#tab-identified > span', { timeout: 7000 }).click()
        cy.get('[data-row-key="100"] > :nth-child(2) > .ph-no-capture').should('contain', '@')
        cy.wait(200)
        cy.location('pathname').should('eq', '/people?category=identified')
        cy.get('#tab-anonymous > span').click()
        cy.wait(200)
        cy.location('pathname').should('eq', '/people?category=anonymous')
        cy.get('.ant-empty-img-simple', { timeout: 7000 }).should('exist')
    })

    it('All people route works', () => {
        cy.get('[data-attr=menu-item-cohorts]').click()
        cy.get('[data-attr=menu-item-all-people]').click()

        cy.get('h1').should('contain', 'Users')
    })
})

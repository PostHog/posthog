describe('People', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click()
    })

    it('People loaded', () => {
        cy.get('h1').should('contain', 'Persons')
    })

    it('Go to new cohort from people screen', () => {
        cy.get('[data-attr=create-cohort]').click()
        cy.get('span').should('contain', 'New Cohort')
    })

    it('All tabs work', () => {
        cy.get('.form-control').type('has:email').type('{enter}').should('have.value', 'has:email')
        cy.wait(200)
        cy.get('.ant-tabs-nav-list > :nth-child(2)').click()
        cy.get('[data-row-key="100"] > :nth-child(2) > .ph-no-capture').should('contain', '@')
        cy.get('.ant-tabs-nav-list > :nth-child(3)').click()
        cy.wait(200)
        cy.get('.ant-empty-img-simple').should('exist')
    })

    it('All people route works', () => {
        cy.get('[data-attr=menu-item-people-cohorts]').click()
        cy.get('[data-attr=menu-item-people-persons]').click()

        cy.get('h1').should('contain', 'Persons')
    })
})

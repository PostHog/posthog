describe('Persons', () => {
    beforeEach(() => {
        // TODO: Remove when releasing navigation-1775
        cy.get('[data-attr=menu-item-people]').click()
    })

    it('People loaded', () => {
        cy.get('h1').should('contain', 'Persons')
    })

    it('All tabs work', () => {
        cy.get('[data-attr=persons-search]').type('has:email').type('{enter}').should('have.value', 'has:email')
        cy.wait(200)
        cy.get('.ant-tabs-nav-list > :nth-child(2)').click()
        cy.get('[data-row-key="100"] > :nth-child(2) > .ph-no-capture').should('contain', '@')
        cy.get('.ant-tabs-nav-list > :nth-child(3)').click()
        cy.wait(200)
        cy.get('.ant-empty-img-simple').should('exist')
    })

    it('Person & cohorts routes works', () => {
        cy.get('[data-attr=menu-item-cohorts]').click()
        cy.get('h1').should('contain', 'Cohorts')

        cy.get('[data-attr=menu-item-persons]').click()
        cy.get('h1').should('contain', 'Persons')
    })
})

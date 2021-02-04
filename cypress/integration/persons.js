describe('Persons', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-persons]').click()
    })

    it('People loaded', () => {
        cy.get('h1').should('contain', 'Persons')
    })

    it('All tabs work', () => {
        cy.get('[data-attr=persons-search]').type('has:email').type('{enter}').should('have.value', 'has:email')
        cy.wait(200)
        cy.get('.ant-tabs-nav-list > :nth-child(2)').click()
        cy.get('[data-row-key]').its('length').should('be.gte', 10)
        cy.get('[data-row-key="9"] > :nth-child(2) > .ph-no-capture').should('contain', '@')
        cy.get('.ant-tabs-nav-list > :nth-child(3)').click()
        cy.wait(200)
        cy.get('.ant-empty-img-simple').should('exist')
    })
})

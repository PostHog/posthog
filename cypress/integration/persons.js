describe('Persons', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
    })

    it('People loaded', () => {
        cy.get('h1').should('contain', 'Persons')
    })

    it('All tabs work', () => {
        cy.get('[data-attr=persons-search]').type('has:email').type('{enter}').should('have.value', 'has:email')
        cy.wait(200)
        cy.get('.ant-radio-group > :nth-child(2)').click()
        cy.get('[data-row-key]').its('length').should('be.gte', 10)
        cy.get('.person-header.identified > .ph-no-capture').should('contain', '@')
        cy.get('.ant-radio-group > :nth-child(3)').click()
        cy.wait(200)
        cy.get('.ant-empty-img-simple').should('exist') // No results placeholder
    })
})

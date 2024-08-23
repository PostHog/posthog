describe('Persons', () => {
    beforeEach(() => {
        cy.clickNavMenu('personsmanagement')
    })

    it('All tabs work', () => {
        cy.get('h1').should('contain', 'People')
        cy.get('[data-attr=persons-search]').type('marisol').type('{enter}').should('have.value', 'marisol')
        cy.wait(200)
        cy.get('[data-row-key]').its('length').should('be.gte', 0)
    })

    it('Deleting person from list', () => {
        cy.get('[data-attr=persons-search]').type('hodge').type('{enter}')
        cy.contains('tr', 'hodge.espinoza@cubix.io').find('[data-attr=delete-person]').click()
        cy.get('h3').should('have.text', 'Are you sure you want to delete "hodge.espinoza@cubix.io"?')
        cy.get('label').contains('I understand').click() // Acknowledge deletion
        cy.get('.LemonButton--secondary').contains('Delete person').click()
        cy.get('.Toastify__toast-body').contains('hodge.espinoza@cubix.io was removed from the project')
        cy.get('tr').contains('hodge.espinoza@cubix.io').should('not.exist')
    })
})

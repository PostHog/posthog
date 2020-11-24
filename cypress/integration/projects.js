describe('Project', () => {
    it('Delete and create only project', () => {
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=menu-item-project-settings]').click()
        cy.get('h1').should('contain', 'Project Settings')
        cy.get('[data-attr=delete-project-button]').click()
        cy.get('.ant-modal-title').should('contain', 'Creating a Project')
        cy.get('.ant-btn-primary').click()
        cy.get('.ant-alert').should('contain', 'Your project needs a name!')
        cy.get('input').type('Project X').should('have.value', 'Project X')
        cy.get('.ant-btn-primary').click()
        cy.get('[data-attr=user-project-dropdown]').should('contain', 'Project X')
    })
})

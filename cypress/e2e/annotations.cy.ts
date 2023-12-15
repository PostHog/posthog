describe('Annotations', () => {
    beforeEach(() => {
        cy.clickNavMenu('datamanagement')
        cy.get('[data-attr=data-management-annotations-tab]').click()
    })

    it('Annotations loaded', () => {
        cy.get('h2').should('contain', 'Create your first annotation')
        cy.get('[data-attr="product-introduction-docs-link"]').should('contain', 'Learn more')
    })

    it('Create annotation', () => {
        cy.get('.page-buttons [data-attr=create-annotation]').click()
        cy.get('[data-attr=create-annotation-input]').type('Test Annotation')
        cy.get('[data-attr=create-annotation-submit]').click()
        cy.get('[data-attr=annotations-table]').contains('Test Annotation').should('exist')
        cy.get('h2').should('not.have.text', 'Create your first annotation')
    })
})

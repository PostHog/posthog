describe('Annotations', () => {
    beforeEach(() => {
        cy.clickNavMenu('annotations')
    })

    it('Annotations loaded', () => {
        cy.get('h1').should('contain', 'Annotations')
    })

    it('Create annotation', () => {
        cy.get('[data-attr=create-annotation]').click()
        cy.get('[data-attr=create-annotation-input]').type('Test Annotation')
        cy.get('[data-attr=create-annotation-submit]').click()
        cy.get('[data-attr=annotations-table]').contains('Test Annotation').should('exist')
    })
})

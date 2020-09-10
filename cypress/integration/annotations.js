describe('Annotations', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-settings]', { timeout: 7000 }).click()
        cy.get('[data-attr=menu-item-annotations]', { timeout: 7000 }).click()
    })

    it('Annotations loaded', () => {
        cy.get('h1').should('contain', 'Annotations')
    })

    it('Create annotation', () => {
        cy.get('[data-attr=create-annotation]').click()
        cy.get('[data-attr=create-annotation-input]').type('Test Annotation')
        cy.get('[data-attr=create-annotation-submit]').click()
        cy.contains('Test Annotation').should('exist')
    })
})

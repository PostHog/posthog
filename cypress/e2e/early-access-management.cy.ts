describe('Early Access Management', () => {
    beforeEach(() => {
        cy.visit('/early_access_features')
    })

    it('Early access feature new and list', () => {
        // load an empty early access feature page
        cy.get('h1').should('contain', 'Early Access Management')
        cy.title().should('equal', 'Early Access Management • PostHog')
        cy.get('h2').should('contain', 'Create your first feature')
        cy.get('[data-attr="product-introduction-docs-link"]').should(
            'contain',
            'Learn more about Early access features'
        )

        // go to create a new feature
        cy.get('[data-attr="create-feature"]').click()

        // New Feature Release page
        cy.get('h1').should('contain', 'New Feature Release')

        // set feature name & description
        cy.get('[data-attr="feature-name"]').type('Test Feature')

        // save
        cy.get('[data-attr="save-feature"]').click()
        cy.get('[data-attr=success-toast]').contains('Early Access Feature saved').should('exist')

        // back to features
        cy.visit('/early_access_features')
        cy.get('tbody').contains('Test Feature')
        cy.get('h2').should('not.have.text', 'Create your first feature')
    })
})

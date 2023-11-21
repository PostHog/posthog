describe('Early Access Management', () => {
    beforeEach(() => {
        cy.visit('/early_access_features')
    })

    it('Early access feature new and list', () => {
        // load an empty early access feature page
        cy.get('h1').should('contain', 'Early Access Management')
        cy.title().should('equal', 'Early access features • PostHog')
        cy.get('h2').should('contain', 'Create your first feature')
        cy.get('[data-attr="product-introduction-docs-link"]').should(
            'contain',
            'Learn more about Early access features'
        )

        // go to create a new feature
        cy.get('[data-attr="create-feature"]').click()

        // New Feature Release page
        cy.get('h1').should('contain', 'New Feature Release')

        // cancel new feature
        cy.get('[data-attr="cancel-feature"]').click()
        cy.get('h1').should('contain', 'Early Access Management')

        // set feature name & description
        cy.get('[data-attr="create-feature"]').click()
        cy.get('[data-attr="feature-name"]').type('Test Feature')
        cy.get('[data-attr="save-feature').should('contain.text', 'Save as draft')

        // save
        cy.get('[data-attr="save-feature"]').click()
        cy.get('[data-attr=success-toast]').contains('Early Access Feature saved').should('exist')

        // back to features
        cy.visit('/early_access_features')
        cy.get('tbody').contains('Test Feature')
        cy.get('h2').should('not.have.text', 'Create your first feature')

        // edit feature
        cy.get('a.Link').contains('.row-name', 'Test Feature').click()
        cy.get('[data-attr="edit-feature"]').click()
        cy.get('h1').should('contain', 'Test Feature')
        cy.get('[data-attr="save-feature"]').should('contain.text', 'Save')

        // delete feature
        cy.get('[data-attr="save-feature"]').click()
        cy.get('[data-attr="delete-feature"]').click()
        cy.get('h3').should('contain', 'Permanently delete feature?')
        cy.get('[data-attr="confirm-delete-feature"]').click()
        cy.get('[data-attr=info-toast]')
            .contains('Early access feature deleted. Remember to delete corresponding feature flag if necessary')
            .should('exist')
    })
})

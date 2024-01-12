describe('Early Access Management', () => {
    beforeEach(() => {
        cy.visit('/early_access_features')
    })

    it('Early access feature new and list', () => {
        // load an empty early access feature page
        cy.get('h1').should('contain', 'Early access features')
        cy.title().should('equal', 'Early access features • PostHog')
        cy.contains('Create your first feature').should('exist')
        cy.get('[data-attr="product-introduction-docs-link"]').should('contain', 'Learn more')

        // go to create a new feature
        cy.get('[data-attr="create-feature"]').click()

        // cancel new feature
        cy.get('[data-attr="cancel-feature"]').click()
        cy.get('h1').should('contain', 'Early access features')

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
        cy.contains('Create your first feature').should('not.exist')

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

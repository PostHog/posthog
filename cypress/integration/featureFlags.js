describe('Feature Flags', () => {
    beforeEach(() => {
        cy.visit('/experiments/feature_flags')
    })

    it('Create feature flag', () => {
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-name').type('beta feature').should('have.value', 'beta feature')
        cy.get('[data-attr=feature-flag-key').should('have.value', 'beta-feature')
        cy.get('[data-attr=feature-flag-switch').click()
        cy.get('[data-attr=feature-flag-submit').click()
        cy.get('[data-attr=feature-flag-table').should('contain', 'beta feature')

        cy.get('[data-attr=feature-flag-table] tr:first-child td:first-child').click()
        cy.get('[data-attr=feature-flag-name').type(' updated').should('have.value', 'beta feature updated')
        cy.get('[data-attr=feature-flag-submit').click()
        cy.get('[data-attr=feature-flag-table').should('contain', 'beta feature updated')
    })

    it('Delete feature flag', () => {
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-name').type('to be deleted').should('have.value', 'to be deleted')
        cy.get('[data-attr=feature-flag-key').should('have.value', 'to-be-deleted')
        cy.get('[data-attr=feature-flag-switch').click()
        cy.get('[data-attr=feature-flag-submit').click()
        cy.get('[data-attr=feature-flag-table').should('contain', 'to be deleted')
        cy.get('[data-row-key="to-be-deleted"]').click()
        cy.get('[data-attr=delete-flag]').click()
        cy.contains('Click here to undo').should('exist')
    })
})

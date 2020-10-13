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
})

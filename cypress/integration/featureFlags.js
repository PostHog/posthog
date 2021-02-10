describe('Feature Flags', () => {
    beforeEach(() => {
        cy.visit('/feature_flags')
    })

    it('Create feature flag', () => {
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-name').type('beta feature').should('have.value', 'beta feature')
        cy.get('[data-attr=feature-flag-key').should('have.value', 'beta-feature')

        // select "add filter" and "property"
        cy.get('[data-attr=new-prop-filter-feature-flag-undefined-0-1').click()

        // select the first property
        cy.get('[data-attr=property-filter-dropdown]').click()
        cy.get('[data-attr=prop-filter-person-0]').click({ force: true })

        // selects the first value
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        cy.get('[data-attr=feature-flag-switch').click()
        cy.get('[data-attr=feature-flag-submit').click()
        cy.get('[data-attr=feature-flag-table').should('contain', 'beta feature')
        cy.get('[data-attr=feature-flag-table').should('contain', '30%')
        cy.get('[data-attr=feature-flag-table').should('contain', 'is_demo')

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
        cy.contains('Click to undo').should('exist')
    })
})

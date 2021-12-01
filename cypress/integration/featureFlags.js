describe('Feature Flags', () => {
    beforeEach(() => {
        cy.visit('/feature_flags')
    })

    it('Create feature flag', () => {
        // ensure unique names to avoid clashes
        const name = 'beta-feature' + Math.floor(Math.random() * 10000000)
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-key]').type(name).should('have.value', name)
        cy.get('[data-attr=feature-flag-description]')
            .type('This is a new feature.')
            .should('have.value', 'This is a new feature.')

        // select "add filter" and "property"
        cy.get('[data-attr=new-prop-filter-feature-flag-null-0-1-').click()

        // select the first property
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('is_demo')
        cy.get('[data-attr=taxonomic-tab-person_properties]').click()
        cy.get('[data-attr=prop-filter-person_properties-0]').click({ force: true })

        // selects the first value
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        // save the feature flag
        cy.get('[data-attr=feature-flag-submit]').click()

        // make sure the data is there as expected after a page reload!
        cy.reload()

        // click the sidebar item to go back to the list
        cy.get('[data-attr=menu-item-featureflags]').click()
        cy.get('[data-attr=feature-flag-table]').should('contain', name)
        cy.get('[data-attr=feature-flag-table]').should('not.contain', '%') // By default it's released to everyone, if a % is not specified
        cy.get('[data-attr=feature-flag-table]').should('contain', 'is_demo')

        cy.get(`[data-row-key=${name}]`).contains(name).click()
        cy.get('[data-attr=feature-flag-key]')
            .type('-updated')
            .should('have.value', name + '-updated')
        cy.get('[data-attr=feature-flag-submit]').click()
        cy.get('.Toastify__toast-body').click() // clicking the toast gets you back to the list
        cy.get('[data-attr=feature-flag-table]').should('contain', name + '-updated')

        cy.get(`[data-row-key=${name}-updated] [data-attr=more-button]`).click()
        cy.contains(`Try out in Insights`).click()
        cy.location().should((loc) => {
            expect(loc.pathname.toString()).to.contain('/insight')
        })
    })

    it('Delete feature flag', () => {
        const name = 'to-be-deleted' + Math.floor(Math.random() * 10000000)
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-key]').type(name).should('have.value', name)
        cy.get('[data-attr=feature-flag-submit]').click()
        cy.get('.Toastify__toast-body').click() // clicking the toast gets you back to the list
        cy.get('[data-attr=feature-flag-table]').should('contain', name)
        cy.get(`[data-row-key=${name}]`).contains(name).click()
        cy.get('[data-attr=delete-flag]').click()
        cy.contains('Click to undo').should('exist')
    })
})

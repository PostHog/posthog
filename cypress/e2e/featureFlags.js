describe('Feature Flags', () => {
    let name

    beforeEach(() => {
        name = 'feature-flag-' + Math.floor(Math.random() * 10000000)
        cy.visit('/feature_flags')
    })

    it('Create feature flag', () => {
        // ensure unique names to avoid clashes
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-key]').click().type(`{moveToEnd}${name}`).should('have.value', name)
        cy.get('[data-attr=feature-flag-description]')
            .type('This is a new feature.')
            .should('have.value', 'This is a new feature.')

        // Check that feature flags instructions can be displayed in another code language
        cy.get('[data-attr=feature-flag-instructions-select]').click()
        cy.get('[data-attr=feature-flag-instructions-select-option-PHP]').click()
        cy.get('[data-attr=feature-flag-instructions-snippet]').should(
            'contain',
            /if (PostHog::isFeatureEnabled('.*', 'some distinct id')) {/
        )
        cy.get('[data-attr=feature-flag-instructions-snippet]').should('contain', /    \/\/ do something here/)
        cy.get('[data-attr=feature-flag-instructions-snippet]').should('contain', /}/)
        cy.get('[data-attr=feature-flag-doc-link]').should(
            'have.attr',
            'href',
            'https://posthog.com/docs/integrations/php-integration?utm_medium=in-product&utm_campaign=feature-flag#feature-flags'
        )

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

        // after save there should be a delete button
        cy.get('button[data-attr="delete-flag"]').should('have.text', 'Delete')

        // make sure the data is there as expected after a page reload!
        cy.reload()

        // click the sidebar item to go back to the list
        cy.clickNavMenu('featureflags')
        cy.get('[data-attr=feature-flag-table]').should('contain', name)
        cy.get('[data-attr=feature-flag-table]').should('not.contain', '%') // By default it's released to everyone, if a % is not specified
        cy.get('[data-attr=feature-flag-table]').should('contain', 'is_demo')

        cy.get(`[data-row-key=${name}]`).contains(name).click()
        cy.get('[data-attr=feature-flag-key]')
            .click()
            .type(`{moveToEnd}-updated`)
            .should('have.value', name + '-updated')
        cy.get('[data-attr=feature-flag-submit]').click()
        cy.wait(100)
        cy.clickNavMenu('featureflags')
        cy.get('[data-attr=feature-flag-table]').should('contain', name + '-updated')

        cy.get(`[data-row-key=${name}-updated] [data-attr=more-button]`).click()
        cy.contains(`Try out in Insights`).click()
        cy.location().should((loc) => {
            expect(loc.pathname.toString()).to.contain('/insight')
        })
    })

    it('Delete feature flag', () => {
        cy.get('h1').should('contain', 'Feature Flags')
        cy.get('[data-attr=new-feature-flag]').click()
        cy.get('[data-attr=feature-flag-key]').focus().type(name).should('have.value', name)
        cy.get('[data-attr=feature-flag-submit]').click()

        // after save there should be a delete button
        cy.get('button[data-attr="delete-flag"]').should('have.text', 'Delete')

        cy.clickNavMenu('featureflags')
        cy.get('[data-attr=feature-flag-table]').should('contain', name)
        cy.get(`[data-row-key=${name}]`).contains(name).click()
        cy.get('[data-attr=delete-flag]').click()
        cy.get('.Toastify').contains('Undo').should('be.visible')
    })
})

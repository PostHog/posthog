describe('Cohorts', () => {
    beforeEach(() => {
        cy.clickNavMenu('cohorts')
    })

    it('Cohorts new and list', () => {
        // load an empty page
        cy.get('h1').should('contain', 'Cohorts')
        cy.title().should('equal', 'Cohorts • PostHog')
        cy.get('h2').should('contain', 'Create your first cohort')
        cy.get('[data-attr="product-introduction-docs-link"]').should('contain', 'Learn more about Cohorts')

        // go to create a new cohort
        cy.get('[data-attr="create-cohort"]').click()

        // select "add filter" and "property"
        cy.get('[data-attr="cohort-selector-field-value"]').click()
        cy.get('[data-attr="cohort-personPropertyBehavioral-have_property-type"]').click()
        cy.get('[data-attr="cohort-taxonomic-field-key"]').click()

        // select the first property
        cy.get('[data-attr=taxonomic-filter-searchfield]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type('is_demo')
        cy.get('[data-attr=prop-filter-person_properties-0]').click({ force: true })
        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })
        cy.get('[data-attr="cohort-name"]').click()

        // set cohort name & description
        cy.get('[data-attr="cohort-name"]').type('Test Cohort')

        // save
        cy.get('[data-attr="save-cohort"]').click()
        cy.get('[data-attr=success-toast]').contains('Cohort saved').should('exist')

        // back to cohorts
        cy.clickNavMenu('cohorts')
        cy.get('tbody').contains('Test Cohort')
        cy.get('h2').should('not.have.text', 'Create your first cohort')

        it('Cohorts new and list', () => {
            cy.get('[data-row-key]').first().click()
            cy.get('[data-test-goto-person]').first().click()
            cy.url().should('include', '/person/')

            cy.get('[data-attr="persons-cohorts-tab"]').click()
            cy.get('[data-row-key]').first().click()

            cy.get('div:not(disabled) > [data-attr="persons-cohorts-tab"]').click()
            cy.get('[data-row-key]').first().click()

            cy.url().should('include', '/cohorts/')
            cy.get('[data-attr="cohort-name"]').should('have.value', 'Test Cohort')
        })

        // back into cohort
        cy.get('tbody').contains('Test Cohort').click()

        // duplicate cohort (dynamic)
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Duplicate as dynamic cohort').click()
        cy.get('.Toastify__toast-body').contains('View cohort').click()

        // duplicate cohort (static)
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Duplicate as static cohort').click()
        cy.get('.Toastify__toast-body').contains('View cohort').click()

        // delete cohort
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Delete cohort').click()
        cy.clickNavMenu('cohorts')
        cy.get('tbody').should('not.have.text', 'Test Cohort (dynamic copy) (static copy)')
    })
})

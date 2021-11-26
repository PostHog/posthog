describe('Cohorts', () => {
    beforeEach(() => {
        cy.clickNavMenu('cohorts')
    })

    it('Cohorts new and list', () => {
        // load an empty page
        cy.get('h1').should('contain', 'Cohorts')
        cy.title().should('equal', 'Cohorts • PostHog')

        // go to create a new cohort
        cy.get('[data-attr="create-cohort"]').click()

        // select "add filter" and "property"
        cy.get('[data-attr="property-filter-0"] button').first().click()

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
        cy.get('[data-attr=success-toast]').should('exist')

        // back to cohorts
        cy.get('.ant-drawer-close').click({ force: true })
        cy.get('tbody').contains('Test Cohort')

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
    })
})

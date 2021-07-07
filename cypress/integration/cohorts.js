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
        cy.get('[data-attr="cohort-choice-definition"]').click()
        cy.get('[data-attr="cohort-name"]').type('Test Cohort')

        // select "add filter" and "property"
        cy.get('.ant-radio-group > :nth-child(2)').click()
        cy.get('[data-attr="new-prop-filter-cohort_0"]').click()

        // select the first property
        cy.get('[data-attr=property-filter-dropdown]').click()
        cy.get('[data-attr=property-filter-dropdown]').type('is_demo')
        cy.get('[data-attr=prop-filter-person-0]').click({ force: true })

        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })
        cy.get('[data-attr="cohort-name"]').click()

        // save
        cy.get('[data-attr="save-cohort"]').click()
        cy.get('[data-attr=success-toast]').should('exist')

        // back to cohorts
        cy.get('.ant-drawer-close').click({ force: true })
        cy.get('.ant-table-tbody').contains('Test Cohort')

        // Navigate to person and back again
        cy.log('Can navigate to person and back again')

        cy.get('[data-test-cohort-row]').first().click()
        cy.get('[data-test-goto-person]').first().click()
        cy.url().should('include', '/person/')

        cy.get('div:not(disabled) > [data-attr="persons-cohorts-tab"]').click()
        cy.get('[data-test-cohort-row]').first().click()

        cy.url().should('include', '/cohorts/')
        cy.get('[data-attr="cohort-name"]').should('have.value', 'Test Cohort')
    })
})

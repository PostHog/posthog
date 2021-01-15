describe('Cohorts', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click() // TODO: Remove when releasing navigation-1775
        cy.get('[data-attr=menu-item-cohorts]').click()
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
        cy.get('[data-attr=prop-filter-person-0]').click({ force: true })

        cy.get('[data-attr=prop-val]').click()
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        // save
        cy.get('[data-attr="save-cohort"]').click()
        cy.get('[data-attr=success-toast]').should('exist')

        // back to cohorts
        cy.get('.ant-drawer-close').click({ force: true })
        cy.get('.ant-table-tbody').contains('Test Cohort')
    })
})

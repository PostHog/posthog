describe('Actions', () => {
    beforeEach(() => {
        cy.clickNavMenu('events')
        cy.get('[data-attr=events-actions-tab]').click()
    })

    it('Create action', () => {
        let name = Cypress._.random(0, 1e6)
        cy.get('[data-attr=create-action]').click()
        cy.get('.ant-card-head-title').should('contain', 'event or pageview')
        cy.get('[data-attr=new-action-pageview]').click()
        cy.get('h1').should('contain', 'Creating action')

        cy.get('[data-attr=edit-action-input]').type(name)
        cy.get('.ant-radio-group > :nth-child(3)').click()
        cy.get('[data-attr=edit-action-url-input]').type(Cypress.config().baseUrl)
        cy.wait(300)
        cy.focused().should('have.attr', 'data-attr', 'edit-action-url-input')

        cy.get('[data-attr=save-action-button]').click()

        cy.contains('Action saved').should('exist')

        // Test the action is immediately available
        cy.clickNavMenu('insights')

        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type(name)
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.get('[data-attr=prop-filter-actions-0]').click()
        cy.get('[data-attr=trend-element-subject-1] span').should('contain', name)
    })

    it('Click on an action', () => {
        cy.get('[data-attr=actions-table]').should('exist')
        cy.get('[data-attr=action-link-0]').click()
        cy.get('h1').should('contain', 'Editing action')
    })
})

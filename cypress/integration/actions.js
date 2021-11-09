describe('Actions', () => {
    let actionName = Cypress._.random(0, 1e6)
    beforeEach(() => {
        cy.clickNavMenu('events')
        cy.get('[data-attr=events-actions-tab]').click()
    })

    it('Create action', () => {
        cy.get('[data-attr=create-action]').click()
        cy.get('.ant-card-head-title').should('contain', 'event or pageview')
        cy.get('[data-attr=new-action-pageview]').click()
        cy.get('h1').should('contain', 'Creating action')

        cy.get('[data-attr=edit-action-input]').type(actionName)
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
        cy.get('[data-attr=taxonomic-filter-searchfield]').type(actionName)
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.get('[data-attr=prop-filter-actions-0]').click()
        cy.get('[data-attr=trend-element-subject-1] span').should('contain', actionName)
    })

    it('Notifies when an action with this name already exists', () => {
        // Let's create a whole new action, similarly to "Create action"
        cy.get('[data-attr=create-action]').click()
        cy.get('[data-attr=new-action-pageview]').click()
        // This time we'll use a "Custom event" type match group
        cy.get('[data-attr=edit-action-input]').type(actionName)
        cy.get('.ant-radio-group > :nth-child(2)').click()
        // Let's save the action
        cy.get('[data-attr=save-action-button]').click()
        // Oh noes, there already is an action with name `actionName`
        cy.contains('Action with this name already exists').should('exist')
        // Let's see it
        cy.contains('Click here to edit').click()
        // We should now be seeing the action from "Create action"
        cy.get('[data-attr=edit-action-url-input]').should('have.value', Cypress.config().baseUrl)
    })

    it('Click on an action', () => {
        cy.get('[data-attr=actions-table]').should('exist')
        cy.get('[data-attr=action-link-0]').click()
        cy.get('h1').should('contain', 'Editing action')
    })
})

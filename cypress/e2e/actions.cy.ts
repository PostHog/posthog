const createAction = (actionName: string): void => {
    cy.get('[data-attr=create-action]').first().click()
    cy.get('.LemonButton').should('contain', 'From event or pageview')
    cy.get('[data-attr=new-action-pageview]').click({ force: true })
    cy.get('input[name="item-name-large"]').should('exist')

    cy.get('input[name="item-name-large"]').type(actionName)
    cy.get('[data-attr=action-type-pageview]').click() // Click "Pageview"
    cy.get('[data-attr=edit-action-url-input]').click().type(Cypress.config().baseUrl)

    cy.get('[data-attr=save-action-button]').first().click()

    cy.contains('Action saved').should('exist')
}

function navigateToActionsTab(): void {
    cy.clickNavMenu('datamanagement')
    cy.get('[data-attr=data-management-actions-tab]').click()
}

describe('Action Events', () => {
    let actionName
    beforeEach(() => {
        navigateToActionsTab()
        actionName = Cypress._.random(0, 1e6)
    })

    it('Create action event', () => {
        createAction(actionName)

        // Test the action is immediately available
        cy.clickNavMenu('insight')
        cy.get('[data-attr="menu-item-insight"]').click()

        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.get('[data-attr=taxonomic-filter-searchfield]').type(actionName)
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.get('[data-attr=prop-filter-actions-0]').click()
        cy.get('[data-attr=trend-element-subject-1] span').should('contain', actionName)
    })

    it('Notifies when an action event with this name already exists', () => {
        createAction(actionName)
        navigateToActionsTab()
        createAction(actionName)
        // Oh noes, there already is an action with name `actionName`
        cy.contains('Action with this name already exists').should('exist')
        // Let's see it
        cy.contains('Edit it here').click()
        // We should now be seeing the action from "Create action"
        cy.get('[data-attr=edit-action-url-input]').should('have.value', Cypress.config().baseUrl)
    })

    it('Click on an action', () => {
        cy.get('[data-attr=actions-table]').should('exist')
        cy.get('[data-attr=action-link-0]').click()
        cy.get('[data-attr=edit-prop-item-name-large]').should('exist')
    })
})

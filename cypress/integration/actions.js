describe('Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
        cy.get('[data-attr=menu-item-actions]').click()
    })

    it('Actions loaded', () => {
        cy.get('h1').should('contain', 'Actions')
    })

    it('Click on an action', () => {
        cy.get('[data-attr=action-link-0]').click()
        cy.get('h1').should('contain', 'Edit action')
    })

    it('Go to new action screen', () => {
        cy.get('[data-attr=create-action]').click()
        cy.get('h1').should('contain', 'New action')
    })

    it('Create action', () => {
        cy.get('[data-attr=create-action]').click()

        cy.get('[data-attr=edit-action-input]').type(Cypress._.random(0, 1e6))
        cy.get('[data-attr=action-step-pageview]').click()
        cy.get('[data-attr=edit-action-url-input]').type(Cypress.config().baseUrl)
        cy.get('[data-attr=save-action-button]').click()

        cy.contains('Action Saved').should('exist')
    })
})

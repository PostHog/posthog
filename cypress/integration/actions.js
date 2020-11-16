describe('Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
        cy.get('[data-attr=events-actions-tab]').click()
    })

    it('Actions loaded', () => {
        cy.get('[data-attr=actions-table]').should('exist')
    })

    it('Click on an action', () => {
        cy.get('[data-attr=action-link-0]').click()
        cy.get('h1').should('contain', 'Editing action')
    })

    it('Create action', () => {
        cy.get('[data-attr=create-action]').click()
        cy.get('.ant-card-head-title').should('contain', 'event or pageview')
        cy.get('[data-attr=new-action-pageview]').click()
        cy.get('h1').should('contain', 'Creating action')

        cy.get('[data-attr=edit-action-input]').type(Cypress._.random(0, 1e6))
        cy.get('.ant-radio-group > :nth-child(3)').click()
        cy.get('[data-attr=edit-action-url-input]').type(Cypress.config().baseUrl)
        cy.get('[data-attr=save-action-button]').click()

        cy.contains('Action saved').should('exist')
    })
})

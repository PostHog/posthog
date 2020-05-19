describe('Actions', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-events]').click()
        cy.get('[data-attr=menu-item-actions]').click()
    })

    it('Actions loaded', () => {
        cy.get('h1').should('contain', 'Actions')
    })

    it('Go to new action screen', () => {
        cy.get('[data-attr=create-action]').click()
        cy.get('h1').should('contain', 'New action')
    })
})

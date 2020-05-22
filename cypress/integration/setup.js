describe('Setup', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-setup]').click()
    })

    it('Setup loaded', () => {
        cy.get('[data-attr=layout-content]').should('exist')
    })
})

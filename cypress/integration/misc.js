describe('Misc', () => {
    it('Changelog', () => {
        cy.get('[data-attr=version-status-button]').click()
        cy.get('[data-attr=changelog-modal]').should('exist')
    })
})

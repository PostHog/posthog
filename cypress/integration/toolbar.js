describe('Toolbar', () => {
    it('Toolbar loads', () => {
        cy.visit('/demo')
        cy.get('#__POSTHOG_TOOLBAR__').should('exist')
    })
})

describe('Toolbar', () => {
    beforeEach(() => {
        cy.visit('/demo')
    })

    it('Toolbar loads', () => {
        cy.get('#__POSTHOG_TOOLBAR__').should('exist')
    })
})

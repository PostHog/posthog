describe('Toolbar', () => {
    beforeEach(() => {
        cy.visit('/demo')
        cy.wait(200)
    })

    it('Toolbar loads', () => {
        cy.get('#__POSTHOG_TOOLBAR__').should('exist')
    })
})

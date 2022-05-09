describe('Preflight', () => {
    beforeEach(() => {
        cy.visit('/logout')
        cy.visit('/preflight')
    })

    it('Preflight experimentation', () => {
        cy.get('[data-attr=preflight-experimentation]').click()
        cy.get('[data-attr=preflight-refresh]').should('be.visible')
        cy.get('[data-attr=caption]').should('contain', 'Not required for experimentation mode')
        cy.wait(200)
        cy.get('[data-attr=preflight-complete]').should('be.visible')
        cy.get('[data-attr=preflight-complete]').click()
        cy.url().should('include', '/signup')
    })

    it('Preflight live mode', () => {
        cy.get('[data-attr=preflight-live]').click()
        cy.get('[data-attr=preflight-refresh]').click()
        cy.get('[data-attr=caption]').should('contain', 'Set up before ingesting real user data')
        cy.wait(200)
        cy.get('[data-attr=preflight-complete]').should('be.visible')
    })
})

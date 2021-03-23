describe('Preflight', () => {
    beforeEach(() => {
        cy.visit('/logout')
        cy.visit('/preflight')
    })

    it('Preflight experimentation', () => {
        cy.get('[data-attr=preflight-experimentation]').click()
        cy.get('[data-attr=preflight-refresh]').should('be.visible')
        cy.get('[data-attr=caption]').should('contain', 'Not required for development or testing')
        cy.wait(200)
        cy.get('[data-attr=preflightStatus]').should('contain', 'All systems go!')
        cy.get('[data-attr=preflight-complete]').click()
        cy.url().should('include', '/signup')
    })

    it('Preflight live mode', () => {
        cy.get('[data-attr=preflight-live]').click()
        cy.get('[data-attr=preflight-refresh]').should('be.visible')
        cy.get('[data-attr=caption]').should('contain', 'Install before ingesting real user data')
        cy.wait(200)
        cy.get('[data-attr=preflightStatus]').should('contain', 'All systems go!')
    })
})

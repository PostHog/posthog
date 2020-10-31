describe('Feature Flags', () => {
    beforeEach(() => {
        cy.visit('/feature_flags')
    })

    it('Create feature flag', () => {
        cy.findByRole('heading', { name: /Feature flags/i })
        cy.findByRole('button', { name: /New Feature Flag/i }).click()
        cy.findByRole('textbox', { name: /Name/i }).type('beta feature').should('have.value', 'beta feature')
        cy.findByRole('textbox', { name: /Key/i }).should('have.value', 'beta-feature')
        // cy.findByLabelText(/Feature flag is active/i).click()
        cy.findByLabelText(/Roll out feature to percentage of users/i).click()
        cy.findByRole('button', { name: /Save/i }).click()

        cy.findByRole('cell', { name: 'beta-feature' }).should('be.visible')

        cy.findByRole('heading', { name: /Feature flags/i })
        cy.findByRole('cell', { name: 'beta-feature' }).should('exist').click()
        cy.findByRole('textbox', { name: /Name/i }).type(' updated').should('have.value', 'beta feature updated')
        cy.findByRole('button', { name: /Save feature flag/i }).click()
        cy.findByRole('cell', { name: 'beta feature updated' }).should('exist')
    })

    it('Delete feature flag', () => {
        cy.findByRole('heading', { name: /Feature flags/i })
        cy.findByRole('button', { name: /New Feature Flag/i }).click()
        cy.findByRole('textbox', { name: /Name/i }).type('to be deleted').should('have.value', 'to be deleted')
        cy.findByRole('textbox', { name: /Key/i }).should('have.value', 'to-be-deleted')
        // cy.findByLabelText(/Feature flag is active/i).click()
        cy.findByLabelText(/Roll out feature to percentage of users/i).click()
        cy.findByRole('button', { name: /Save/i }).click()

        cy.findByRole('cell', { name: 'to-be-deleted' }).should('be.visible')

        cy.findByRole('cell', { name: 'to-be-deleted' }).should('exist').click()

        cy.findByRole('button', { name: /Delete/i }).click()

        cy.findByText(/Click here to undo/i).should('exist')
    })
})

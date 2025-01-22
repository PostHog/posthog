describe('Experiments', () => {
    let randomNum
    let experimentName
    let featureFlagKey

    beforeEach(() => {
        cy.intercept('/api/users/@me/', {
            fixture: 'api/experiments/user',
        })

        randomNum = Math.floor(Math.random() * 10000000)
        experimentName = `Experiment ${randomNum}`
        featureFlagKey = `experiment-${randomNum}`
    })

    it('create experiment', () => {
        cy.visit('/experiments')
        cy.get('[data-attr=top-bar-name]').should('contain', 'Experiments')

        // Name, flag key, description
        cy.get('[data-attr=create-experiment]').first().click()
        cy.get('[data-attr=experiment-name]').click().type(`${experimentName}`).should('have.value', experimentName)
        cy.get('[data-attr=experiment-feature-flag-key]')
            .click()
            .type(`${featureFlagKey}`)
            .should('have.value', featureFlagKey)
        cy.get('[data-attr=experiment-description]')
            .click()
            .type('This is the description of the experiment')
            .should('have.value', 'This is the description of the experiment')

        // Edit variants
        cy.get('[data-attr="add-test-variant"]').click()
        cy.get('input[data-attr="experiment-variant-key"][data-key-index="1"]')
            .clear()
            .type('test-variant-1')
            .should('have.value', 'test-variant-1')
        cy.get('input[data-attr="experiment-variant-key"][data-key-index="2"]')
            .clear()
            .type('test-variant-2')
            .should('have.value', 'test-variant-2')

        // Save experiment
        cy.get('[data-attr="save-experiment"]').first().click()
    })
})

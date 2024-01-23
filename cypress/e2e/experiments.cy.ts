describe('Experiments', () => {
    let randomNum
    let experimentName
    let featureFlagKey

    beforeEach(() => {
        cy.intercept('/api/users/@me/', {
            fixture: 'api/experiments/user',
        })

        cy.intercept('/api/projects/1/experiments?limit=1000', {
            fixture: 'api/experiments/experiments',
        })

        cy.intercept('/api/projects/1/experiments/1234/', {
            fixture: 'api/experiments/new-experiment',
        })

        cy.intercept('POST', '/api/projects/1/experiments/', (req) => {
            req.reply({ fixture: 'api/experiments/new-experiment' })
        })

        randomNum = Math.floor(Math.random() * 10000000)
        experimentName = `Experiment ${randomNum}`
        featureFlagKey = `experiment-${randomNum}`
        cy.visit('/experiments')
    })

    it('create experiment', () => {
        cy.get('[data-attr=top-bar-name]').should('contain', 'A/B testing')

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

        // Select goal type
        cy.get('[data-attr="experiment-goal-type-select"]').click()
        cy.contains('Trend').should('be.visible')
        cy.contains('Conversion funnel').should('be.visible')

        // Add secondary metric
        const secondaryMetricName = `Secondary metric ${Math.floor(Math.random() * 10000000)}`
        cy.get('[data-attr="add-secondary-metric-btn"]').click()
        cy.get('[data-attr=secondary-metric-name]')
            .click()
            .type(secondaryMetricName)
            .should('have.value', secondaryMetricName)
        cy.get('[data-attr="metrics-selector"]').click()
        cy.contains('Trends').should('be.visible')
        cy.contains('Funnels').should('be.visible')
        cy.get('[data-attr="create-annotation-submit"]').click()
        cy.contains(secondaryMetricName).should('exist')

        // Edit minimum acceptable improvement
        cy.get('input[data-attr="min-acceptable-improvement"]').type('{selectall}20').should('have.value', '20')

        // Save experiment
        cy.get('[data-attr="save-experiment"]').first().click()
    })
})

import { decideResponse } from '../fixtures/api/decide'

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
        cy.get('.Popover__content').contains('Trend').should('be.visible')
        cy.get('.Popover__content').contains('Conversion funnel').should('be.visible')

        // Add secondary metric
        const secondaryMetricName = `Secondary metric ${Math.floor(Math.random() * 10000000)}`
        cy.get('[data-attr="add-secondary-metric-btn"]').click()
        cy.get('[data-attr=secondary-metric-name]')
            .click()
            .type(secondaryMetricName)
            .should('have.value', secondaryMetricName)
        cy.get('[data-attr="metrics-selector"]').click()
        cy.get('.Popover__content').contains('Funnels').should('be.visible')
        cy.get('.Popover__content').contains('Trends').should('be.visible')
        cy.get('[data-attr="create-annotation-submit"]').click()
        cy.contains(secondaryMetricName).should('exist')

        // Edit minimum acceptable improvement
        cy.get('input[data-attr="min-acceptable-improvement"]').type('{selectall}20').should('have.value', '20')

        // Save experiment
        cy.get('[data-attr="save-experiment"]').first().click()
    })

    const createExperimentInNewUi = () => {
        cy.intercept('**/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'new-experiments-ui': true,
                })
            )
        )
        cy.visit('/experiments')

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

        // Continue creation
        cy.get('[data-attr="continue-experiment-creation"]').first().click()
        // Save experiment
        cy.get('[data-attr="save-experiment"]').first().click()
    }

    it('create, launch and stop experiment with new ui', () => {
        createExperimentInNewUi()
        cy.get('[data-attr="experiment-status"]').contains('draft').should('be.visible')

        cy.get('[data-attr="experiment-creation-date"]').contains('a few seconds ago').should('be.visible')
        cy.get('[data-attr="experiment-start-date"]').should('not.exist')

        cy.get('[data-attr="launch-experiment"]').first().click()
        cy.get('[data-attr="experiment-creation-date"]').should('not.exist')
        cy.get('[data-attr="experiment-start-date"]').contains('a few seconds ago').should('be.visible')

        cy.get('[data-attr="stop-experiment"]').first().click()
        cy.get('[data-attr="experiment-creation-date"]').should('not.exist')
        cy.get('[data-attr="experiment-start-date"]').contains('a few seconds ago').should('be.visible')
        cy.get('[data-attr="experiment-end-date"]').contains('a few seconds ago').should('be.visible')
    })

    it('move start date', () => {
        createExperimentInNewUi()

        cy.get('[data-attr="launch-experiment"]').first().click()

        cy.get('[data-attr="move-experiment-start-date"]').first().click()
        cy.get('[data-attr="experiment-start-date-picker"]').should('exist')
        cy.get('[data-attr="lemon-calendar-month-previous"]').first().click()
        cy.get('[data-attr="lemon-calendar-day"]').first().click()
        cy.get('[data-attr="lemon-calendar-select-apply"]').first().click()
        cy.get('[data-attr="experiment-start-date"]')
            .contains(/months? ago/)
            .should('be.visible')

        cy.reload()

        // Check that the start date persists
        cy.get('[data-attr="experiment-start-date"]')
            .contains(/months? ago/)
            .should('be.visible')
    })
})

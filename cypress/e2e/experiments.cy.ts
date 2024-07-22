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

        // Continue to step 2
        cy.get('[data-attr="continue-experiment-creation"]').click()

        // Goal type selection is visible
        cy.get('[data-attr="experiment-goal-type-select"]')
            .should('be.visible')
            .within(() => {
                cy.contains('Conversion funnel').should('be.visible')
                cy.contains('Trend').should('be.visible')
            })

        // Goal input is visible
        cy.get('[data-attr="experiment-goal-input"]')
            .should('be.visible')
            .within(() => {
                cy.get('li.ActionFilterRow').should('exist')
                cy.get('button').contains('Add funnel step').should('exist')
            })

        // Save experiment
        cy.get('[data-attr="save-experiment"]').first().click()
    })

    const createExperimentInNewUi = (): void => {
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
        // Wait for the dialog to appear and click the confirmation button
        cy.get('.LemonModal__layout').should('be.visible')
        cy.contains('Stop this experiment?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Stop').click()
        // Wait for the dialog to disappear
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

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        cy.visit('/insights')
    })

    it('Stickiness graph', () => {
        cy.get('[id="rc-tabs-0-tab-STICKINESS"]').click()
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
    })

    it('Lifecycle graph', () => {
        cy.get('[id="rc-tabs-0-tab-LIFECYCLE"]').click()
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.get('[data-attr=add-breakdown-button]').should('not.exist') // Can't do breakdown on this graph
        cy.get('[data-attr=add-action-event-button]').should('not.exist') // Can't add multiple series
    })

    it('Loads default filters correctly', () => {
        cy.visit('/events') // Test that default params are set correctly even if the app doesn't start on insights
        cy.reload()

        cy.get('[data-attr=menu-item-insights]').click()
        cy.get('[data-attr=trend-element-subject-0] span').should('contain', '$pageview')
        cy.get('[data-attr=trend-line-graph]').should('exist')
        cy.contains('Add graph series').click()
        cy.get('[data-attr=trend-element-subject-1]').should('exist')
        cy.get('[data-attr=trend-line-graph]').should('exist')
    })
})

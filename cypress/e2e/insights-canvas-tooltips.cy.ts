import { urls } from 'scenes/urls'

// For tests related to trends please check trendsElements.js
// insight tests were split up because Cypress was struggling with this many tests in one file🙈
describe('Insights', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    it('Trend graph tooltip it not empty', () => {
        cy.get('[role=tab]').contains('Trends').click()
        cy.get('[data-attr=date-filter]').click()
        cy.get('.Popover__box .LemonButton__content').contains('Last 14 days').click()
        cy.get('.LineGraph').should('exist')
        cy.get('.LineGraph canvas').trigger('mousemove')
        cy.get('.InsightTooltip .LemonTable').should('exist')
        cy.get('.InsightTooltip .LemonTable .LemonTable__content .LemonTable__boundary .LemonTable__header-content')
            .invoke('text')
            .should('match', /^.+/i)
    })

    it('Funnel historical graph tooltip it not empty', () => {
        cy.get('[role=tab]').contains('Funnels').click()
        cy.get('.EditorFilterGroup button.LemonSelect').contains('Conversion steps').click()
        cy.get('.Popover__box .LemonButton__content').contains('Historical trends').click()
        cy.get('[data-attr=add-action-event-button-empty-state]').click()
        cy.get('[data-attr=date-filter]').click()
        cy.get('.Popover__box .LemonButton__content').contains('Last 30 days').click()
        cy.get('.LineGraph').should('exist')
        cy.get('.LineGraph canvas').trigger('mousemove')
        cy.get('.InsightTooltip .LemonTable').should('exist')
        cy.get('.InsightTooltip .LemonTable .LemonTable__content .LemonTable__boundary')
            .invoke('text')
            .should('match', /^.+/i)
    })

    it('Stickiness graph tooltip it not empty', () => {
        cy.get('[role=tab]').contains('Stickiness').click()
        cy.get('[data-attr=date-filter]').click()
        cy.get('.Popover__box .LemonButton__content').contains('Last 30 days').click()
        cy.get('.LineGraph').should('exist')
        cy.get('.LineGraph canvas').trigger('mousemove')
        cy.get('.InsightTooltip .LemonTable').should('exist')
        cy.get('.InsightTooltip .LemonTable .LemonTable__content .LemonTable__boundary .LemonTable__header-content')
            .invoke('text')
            .should('match', /^\d+\s+days?(.*)$/i)
    })
})

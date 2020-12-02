describe('Funnels', () => {
    beforeEach(() => {
        cy.visit('/')
        cy.get('[data-attr=insight-funnels-tab]').click()
        cy.wait(200)
    })

    it('Add 1 action to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()

        // Double click: https://www.cypress.io/blog/2019/01/22/when-can-the-test-click/
        cy.contains('HogFlix homepage view').click().click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })

    it('Apply date filter to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.contains('HogFlix homepage view').click().click()
        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })

    it('Add 2 actions to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.contains('HogFlix homepage view').click().click()

        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.contains('HogFlix paid').click().click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })
})

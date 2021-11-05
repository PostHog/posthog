const TIMEOUT = 30000 // increase timeout for funnel viz as sometimes github actions can be slow

describe.skip('Funnels', () => {
    beforeEach(() => {
        // :TRICKY: Race condition populating the first dropdown in funnel
        cy.get('[data-test-filters-loading]').should('not.exist')
        cy.get('[data-attr=insight-funnels-tab]').click()
        cy.wait(200)
    })

    it('Add only events to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').first().click()

        cy.get('[data-attr=save-funnel-button]').click() // `save-funnel-button` is actually calculate, keeping around to avoid losing data

        cy.get('[data-attr=funnel-bar-graph]', { timeout: TIMEOUT }).should('exist')
    })

    it('Add 1 action to funnel and navigate to persons', () => {
        cy.get('[data-attr=add-action-event-button]').first().click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('[data-attr=taxonomic-tab-actions]').click()

        cy.wait(200)
        cy.contains('HogFlix homepage view').click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-bar-graph]', { timeout: TIMEOUT }).should('exist')

        cy.get('[data-attr="funnel-person"] a')
            .filter(':contains("@")')
            .first()
            .then(($match) => {
                const email = $match.text()

                cy.wrap($match).click()

                cy.url().should('include', '/person/')
                cy.contains(email).should('exist')
            })
    })

    it('Apply date filter to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').first().click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.contains('HogFlix homepage view').click()
        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=date-filter]').click()
        cy.contains('Last 30 days').click()

        cy.get('[data-attr=funnel-bar-graph]', { timeout: TIMEOUT }).should('exist')
    })

    it('Add 2 actions to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').first().click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.contains('HogFlix homepage view').click()

        cy.get('[data-attr=add-action-event-button]').first().click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.get('[data-attr=taxonomic-tab-actions]').click()
        cy.contains('HogFlix paid').click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-bar-graph]', { timeout: TIMEOUT }).should('exist')
    })
})

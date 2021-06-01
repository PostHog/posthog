describe('Funnels', () => {
    beforeEach(() => {
        cy.get('[data-attr=insight-funnels-tab]').click()
        cy.wait(200)
    })

    it('Add only events to funnel', () => {
        cy.get('[data-attr=add-action-event-button]').click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })

    it('Add 1 action to funnel and navigate to persons', () => {
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()

        cy.wait(200)
        cy.contains('HogFlix homepage view').click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-viz]').should('exist')

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
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.contains('HogFlix homepage view').click()
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
        cy.contains('HogFlix homepage view').click()

        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-1]').click()
        cy.contains('HogFlix paid').click()

        cy.get('[data-attr=save-funnel-button]').click()

        cy.get('[data-attr=funnel-viz]').should('exist')
    })

    // Request line too large issue - https://github.com/PostHog/posthog/issues/4554
    it('Create long funnel', () => {
        cy.get('[data-attr=add-action-event-button]').click()
        cy.get('[data-attr=trend-element-subject-0]').click()
        cy.contains('HogFlix homepage view').click()

        // Create request line that's larger than 4094 bytes by adding action events.
        const iters = Array.from({ length: 50 }, (v, k) => k + 1)
        cy.wrap(iters).each(() => {
            cy.get('[data-attr=add-action-event-button]').click()
        })

        cy.get('[data-attr=save-funnel-button]').click()
        cy.get('[data-attr=funnel-viz]').should('exist')
    })
})

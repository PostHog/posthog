// Mainly testing to make sure events are fired as expected

describe('Billing Upgrade CTA', () => {
    beforeEach(() => {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-unsubscribed.json' })
    })

    it('Check that events are being sent on each page visit', () => {
        cy.visit('/organization/billing')
        cy.get('[data-attr=billing-page-core-upgrade-cta] .LemonButton__content').should('have.text', 'Upgrade now')
        cy.window().then((win) => {
            const events = (win as any)._cypress_posthog_captures
            win.console.warn('_CYPRESS_POSTHOG_CAPTURES', JSON.stringify(events))

            const matchingEvents = events.filter((event) => event.event === 'billing CTA shown')
            // One for each product card
            expect(matchingEvents.length).to.equal(1)
        })

        // Mock billing response with subscription
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing.json' })
        cy.reload()

        cy.get('[data-attr=billing-page-core-upgrade-cta] .LemonButton__content').should('not.exist')
        cy.get('[data-attr=manage-billing]').should('have.text', 'Manage card details and view past invoices')
    })
})

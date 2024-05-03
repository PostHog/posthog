import { decideResponse } from '../fixtures/api/decide'
import * as fflate from 'fflate'

// Mainly testing to make sure events are fired as expected

describe('Billing Upgrade CTA', () => {
    beforeEach(() => {
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2-unsubscribed.json' })
    })

    it('Check that events are being sent on each page visit', () => {
        cy.visit('/organization/billing')
        cy.get('[data-attr=product_analytics-upgrade-cta] .LemonButton__content').should('have.text', 'Subscribe')
        cy.window().then((win) => {
            const events = (win as any)._cypress_posthog_captures

            const matchingEvents = events.filter((event) => event.event === 'billing CTA shown')
            // One for each product card
            expect(matchingEvents.length).to.equal(4)
        })

        // Mock billing response with subscription
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2.json' })
        cy.reload()

        cy.get('[data-attr=session_replay-upgrade-cta] .LemonButton__content').should('have.text', 'Subscribe')
        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture3')
        cy.window().then((win) => {
            const events = (win as any)._cypress_posthog_captures

            const matchingEvents = events.filter((event) => event.event === 'billing CTA shown')
            expect(matchingEvents.length).to.equal(3)
        })

        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2-unsubscribed.json' })
        // Navigate to the onboarding billing step
        cy.visit('/products')
        cy.get('[data-attr=product_analytics-onboarding-card]').click()
        cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(5)').click()

        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture4')
        cy.window().then((win) => {
            const events = (win as any)._cypress_posthog_captures

            const matchingEvents = events.filter((event) => event.event === 'billing CTA shown')
            expect(matchingEvents.length).to.equal(3)
        })
    })
})

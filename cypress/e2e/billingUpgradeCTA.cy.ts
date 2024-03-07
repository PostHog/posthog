import { decideResponse } from '../fixtures/api/decide'
import * as fflate from 'fflate'

// Mainly testing to make sure events are fired as expected

describe('Billing Upgrade CTA', () => {
    beforeEach(() => {
        cy.intercept('https://us.i.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'billing-upgrade-language': 'credit_card',
                })
            )
        )

        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2-unsubscribed.json' })
    })

    it('Check that events are being sent on each page visit', () => {
        cy.visit('/insights')
        // Try to create a new project
        cy.get('[data-attr=breadcrumb-project]').click()
        cy.get('[data-attr=new-project-button]').click()
        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture')
        cy.get('[data-attr=paygate]').should('be.visible')
        cy.get('[data-attr=paygate-mini-cta] .LemonButton__content').should('have.text', 'Add credit card')

        cy.wait('@capture').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON.filter((event) => event.event === 'billing CTA shown')
            expect(matchingEvents.length).to.equal(1)
        })

        cy.visit('/organization/billing')
        cy.get('[data-attr=product_analytics-upgrade-cta] .LemonButton__content').should('have.text', 'Add credit card')
        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture2')
        cy.wait('@capture2').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON.filter((event) => event.event === 'billing CTA shown')
            // One for each product card
            expect(matchingEvents.length).to.equal(4)
        })

        // Mock billing response with subscription
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2.json' })
        cy.reload()

        cy.get('[data-attr=session_replay-upgrade-cta] .LemonButton__content').should('have.text', 'Add paid plan')
        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture3')
        cy.wait('@capture3').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            console.log('fun', decodedJSON)
            const matchingEvents = decodedJSON.filter((event) => event.event === 'billing CTA shown')
            expect(matchingEvents.length).to.equal(4)
        })

        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2-unsubscribed.json' })
        // Navigate to the onboarding billing step
        cy.visit('/products')
        cy.get('[data-attr=product_analytics-onboarding-card]').click()
        cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(5)').click()

        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture4')
        cy.wait('@capture4').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON.filter((event) => event.event === 'billing CTA shown')
            expect(matchingEvents.length).to.equal(1)
        })
    })
})

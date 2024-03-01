import { decideResponse } from '../fixtures/api/decide'
import * as fflate from 'fflate'

// Mainly testing to make sure events are fired as expected

describe('Exporting Insights', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'billing-upgrade-language': 'credit_card',
                })
            )
        )

        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture')
    })

    it('Check that events are being sent on each page visit', () => {
        // Navigate to any page
        cy.visit('/insights')
        // Try to create a new project
        cy.get('[data-attr=breadcrumb-project').click()
        cy.get('[data-attr=new-project-button').click()
        cy.get('[data-attr=upgrade-modal]').should('be.visible')
        cy.wait('@capture').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON.filter((event) => event.event === 'report subscription status')
            expect(matchingEvents.length).to.equal(1)
            expect(matchingEvents[0].properties.has_active_subscription).to.equal(false)
        })

        cy.visit('/organization/billing')
        cy.wait('@capture').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON.filter((event) => event.event === 'report subscription status')
            expect(matchingEvents.length).to.equal(1)
            expect(matchingEvents[0].properties.has_active_subscription).to.equal(false)
        })

        // Mock billing response with subscription
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2.json' })
        cy.reload()
        cy.wait('@capture').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON
                .filter((event) => event.event === 'report subscription status')
                .sort((eventA, eventB) => (new Date(eventA.timestamp) < new Date(eventB.timestamp) ? 1 : -1))
            expect(matchingEvents.length).to.equal(2)
            expect(matchingEvents[0].properties.has_active_subscription).to.equal(true)
        })

        // Navigate to the onboarding billing step
        cy.visit('/products')
        cy.get('[data-attr=product_analytics-onboarding-card]').click()
        cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(5)').click()
        cy.wait('@capture').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            const matchingEvents = decodedJSON
                .filter((event) => event.event === 'report subscription status')
                .sort((eventA, eventB) => (new Date(eventA.timestamp) < new Date(eventB.timestamp) ? 1 : -1))
            expect(matchingEvents.length).to.equal(2)
            console.log(matchingEvents)
            expect(matchingEvents[0].properties.has_active_subscription).to.equal(true)
        })
    })
})

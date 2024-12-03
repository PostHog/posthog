import { insight } from '../productAnalytics'
import { randomString } from '../support/random'

// For tests related to trends please check trendsElements.js
describe('Insights', () => {
    beforeEach(() => {
        // set window:confirm here to ensure previous tests can't block
        cy.on('window:confirm', () => {
            return true
        })

        cy.visit('/insights')
        cy.wait('@getInsights').then(() => {
            cy.get('.saved-insights tr').should('exist')
        })
    })

    describe('unsaved insights confirmation', () => {
        it('can move away from an unchanged new insight without confirm()', () => {
            insight.newInsight()
            cy.log('Navigate away')
            cy.get('[data-attr="menu-item-featureflags"]').click()
            cy.log('We should be on the Feature Flags page now')
            cy.url().should('include', '/feature_flags')
        })

        it('Can navigate away from unchanged saved insight without confirm()', () => {
            const insightName = randomString('to save and then navigate away from')
            insight.create(insightName)

            cy.get('[data-attr="menu-item-dashboards"]').click()

            cy.url().should('include', '/dashboard')
        })

        it('Can keep editing changed new insight after navigating away with confirm() rejection (case 1)', () => {
            cy.on('window:confirm', () => {
                return false
            })

            insight.newInsight()

            cy.log('Add series')
            cy.get('[data-attr=add-action-event-button]').click()

            cy.log('Navigate away')
            cy.get('[data-attr="menu-item-featureflags"]').click()

            cy.log('Save button should still be here because case 1 rejects confirm()')
            cy.get('[data-attr="insight-save-button"]').should('exist')
        })

        it('Can navigate away from changed new insight with confirm() acceptance (case 2)', () => {
            cy.on('window:confirm', () => {
                return true
            })

            insight.newInsight()

            cy.log('Add series')
            cy.get('[data-attr=add-action-event-button]').click()

            cy.log('Navigate away')
            cy.get('[data-attr="menu-item-featureflags"]').click()
            cy.url().should('include', '/feature_flags')
        })
    })
})

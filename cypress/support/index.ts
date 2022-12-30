/// <reference types="cypress" />

declare global {
    // eslint-disable-next-line @typescript-eslint/no-namespace
    namespace Cypress {
        interface Chainable {
            /**
             * Custom command to login to PostHog
             */
            login(): Chainable<Element>

            /**
             * Custom command to click a navigation menu item
             * @example cy.clickNavMenu('dashboards')
             */
            clickNavMenu(name: string): Chainable<Element>
        }
    }
}

export {}

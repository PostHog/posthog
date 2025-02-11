/// <reference types="cypress" />

import { CaptureResult } from 'posthog-js'

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

            /**
             * Custom command to set subscription status
             * @example cy.useSubscriptionStatus('unsubscribed')
             */
            useSubscriptionStatus(name: 'unsubscribed' | 'subscribed'): Chainable<Element>

            /**
             * Custom command to poll until an event is present
             * Waits for up to 5 seconds
             * timeout can be passed as the second parameter
             * @example cy.pollUntilPresent('event_name', 10000)
             */
            pollUntilPresent(eventName: string, timeout?: number): Chainable<CaptureResult[]>
        }
    }
}

export {}

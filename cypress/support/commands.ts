import { CaptureResult } from 'posthog-js'

// KLUDGE duplicated from loadPostHogJS.tsx to "avoid sharing code" between prod and tests
interface WindowWithCypressCaptures extends Window {
    // our Cypress tests will use this to check what events were sent to PostHog
    _cypress_posthog_captures?: CaptureResult[]
    // cypress puts this on the window, so we can check for it to see if Cypress is running
    Cypress?: any
}

Cypress.Commands.add('login', () => {
    // This function isn't used for every test anymore
    cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()

    cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
    cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

    cy.get('[type=submit]').click()

    cy.location('pathname').should('not.eq', '/login') // Wait until login request fully completes
})

Cypress.Commands.add('clickNavMenu', (name) => {
    cy.get(`[data-attr="menu-item-${name}"]`).click()
})

Cypress.Commands.add('useSubscriptionStatus', (condition) => {
    if (condition === 'unsubscribed') {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-unsubscribed.json' })
        cy.reload()
    } else if (condition === 'subscribed') {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-subscribed-all.json' })
        cy.reload()
    }
})

Cypress.Commands.add('pollUntilPresent', (eventName: string, timeout = 5000): Cypress.Chainable<CaptureResult[]> => {
    return cy.window().then({ timeout }, (win: WindowWithCypressCaptures) => {
        return new Cypress.Promise<CaptureResult[]>((resolve, reject) => {
            const checkEvents = (): void => {
                const events = win._cypress_posthog_captures || []
                if (events.some((event) => event.event === eventName)) {
                    resolve(events) // Return the captures array
                } else {
                    setTimeout(checkEvents, 100) // Retry in 100ms
                }
            }
            checkEvents()
            setTimeout(() => reject(new Error(`Timed out waiting for event: ${eventName}`)), timeout)
        })
    })
})

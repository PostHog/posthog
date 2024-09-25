import 'givens/setup'
import './commands'
import 'cypress-axe'

import { urls } from 'scenes/urls'

import { decideResponse } from '../fixtures/api/decide'

try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    require('cypress-terminal-report/src/installLogsCollector')()
    // eslint-disable-next-line no-empty
} catch {}

const E2E_TESTING = Cypress.env('E2E_TESTING')

// Add console errors into cypress logs. This helps with failures in Github Actions which otherwise swallows them.
// From: https://github.com/cypress-io/cypress/issues/300#issuecomment-688915086
Cypress.on('window:before:load', (win) => {
    cy.spy(win.console, 'error')
    cy.spy(win.console, 'warn')

    win._cypress_posthog_captures = []
})

Cypress.on('window:load', (win) => {
    // This is an absolutely mad fix for the Cypress renderer process crashing in CI:
    // https://github.com/cypress-io/cypress/issues/27415#issuecomment-2169155274
    // Hopefully one day #27415 is solved and this becomes unnecessary
    const RealResizeObserver = win.ResizeObserver

    let queueFlushTimeout: number | null = null
    let queue: { cb: ResizeObserverCallback; args: Parameters<ResizeObserverCallback>[0] }[] = []

    /** ResizeObserver wrapper with "enforced batches" */
    class ResizeObserverPolyfill {
        observer: ResizeObserver
        callback: ResizeObserverCallback

        constructor(callback) {
            this.callback = callback
            this.observer = new RealResizeObserver(this.check.bind(this))
        }

        observe(element): void {
            this.observer.observe(element)
        }

        unobserve(element): void {
            this.observer.unobserve(element)
        }

        disconnect(): void {
            this.observer.disconnect()
        }

        check(entries): void {
            // remove previous invocations of "self"
            queue = queue.filter((x) => x.cb !== this.callback)
            // put a new one
            queue.push({ cb: this.callback, args: entries })
            // trigger update
            if (!queueFlushTimeout) {
                queueFlushTimeout = requestAnimationFrame(() => {
                    queueFlushTimeout = null
                    const queueBeingFlushed = queue
                    queue = []
                    for (const q of queueBeingFlushed) {
                        q.cb(q.args, this)
                    }
                })
            }
        }
    }

    win.ResizeObserver = ResizeObserverPolyfill
})

before(() => {
    cy.task('resetInsightCache') // Reset insight cache before each suite
})

beforeEach(() => {
    Cypress.env('POSTHOG_PROPERTY_CURRENT_TEST_TITLE', Cypress.currentTest.title)
    Cypress.env('POSTHOG_PROPERTY_CURRENT_TEST_FULL_TITLE', Cypress.currentTest.titlePath.join(' > '))
    Cypress.env('POSTHOG_PROPERTY_GITHUB_ACTION_RUN_URL', process.env.GITHUB_ACTION_RUN_URL)
    cy.useSubscriptionStatus('subscribed')

    cy.intercept('**/decide/*', (req) =>
        req.reply(
            decideResponse({
                // Feature flag to be treated as rolled out in E2E tests, e.g.:
                // 'toolbar-launch-side-action': true,
            })
        )
    )

    // un-intercepted sometimes this doesn't work and the page gets stuck on the SpinnerOverlay
    cy.intercept(/app.posthog.com\/api\/projects\/@current\/feature_flags\/my_flags.*/, (req) => req.reply([]))
    cy.intercept('https://www.gravatar.com/avatar/**', (req) =>
        req.reply({ statusCode: 404, body: 'Cypress forced 404' })
    )

    cy.intercept('GET', /\/api\/projects\/\d+\/insights\/?\?/).as('getInsights')

    cy.request('POST', '/api/login/', {
        email: 'test@posthog.com',
        password: '12345678',
    })

    if (Cypress.spec.name.includes('before-onboarding')) {
        cy.visit('/?no-preloaded-app-context=true')
    } else if (Cypress.spec.name.includes('organizationSettings')) {
        cy.visit(urls.settings('organization'))
    } else {
        cy.visit('/insights')
        cy.wait('@getInsights').then(() => {
            cy.get('.saved-insights tr').should('exist')
        })
    }
})

afterEach(function () {
    const { state, duration } = this.currentTest
    const event = state === 'passed' ? 'e2e_testing_test_passed' : 'e2e_testing_test_failed'

    if (E2E_TESTING) {
        cy.window().then((win) => {
            ;(win as any).posthog?.capture(event, { state, duration })
        })
    }
})

const resizeObserverLoopErrRe = /^[^(ResizeObserver loop limit exceeded)]/
Cypress.on('uncaught:exception', (err) => {
    /* returning false here prevents Cypress from failing the test */
    if (resizeObserverLoopErrRe.test(err.message)) {
        return false
    }
})

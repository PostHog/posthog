// PROTOTYPE, throwaway: the handoff of the "send your app's emails through PostHog" kind, which starts at email setup.
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

export function openSendFromCodeSetup(source: string): void {
    // pinned: analytics event name, shared with the other messaging calls to action
    posthog.capture('message audience clicked', { source, destination: 'send_from_code' })
    router.actions.push(urls.transactional())
}

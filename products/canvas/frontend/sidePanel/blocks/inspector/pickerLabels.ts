const KNOWN_EVENTS: Record<string, string> = {
    $pageview: 'Pageview',
    $pageleave: 'Pageleave',
    $autocapture: 'Autocapture',
    $screen: 'Screen',
    $identify: 'Identify',
    $exception: 'Exception',
    $web_vitals: 'Web vitals',
    $feature_flag_called: 'Feature flag called',
    $groupidentify: 'Group identify',
    $set: 'Set person properties',
}

/** A readable name for an event: known PostHog events get their label, other `$` events a sentence-case one. */
export function eventLabel(event: string): string {
    if (KNOWN_EVENTS[event]) {
        return KNOWN_EVENTS[event]
    }
    if (!event.startsWith('$')) {
        return event
    }
    const words = event.slice(1).replaceAll('_', ' ')
    return words.charAt(0).toUpperCase() + words.slice(1)
}

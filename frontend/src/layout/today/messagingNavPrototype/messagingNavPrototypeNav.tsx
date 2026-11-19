// PROTOTYPE, never merged: PostHog/michaelr-context#419. The one nav model all three variants render.
import {
    IconCalendar,
    IconCode,
    IconDecisionTree,
    IconDocument,
    IconGear,
    IconHome,
    IconPeople,
    IconPulse,
    IconSend,
    IconServer,
} from '@posthog/icons'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

export const MESSAGING_HOME_PATH = '/messaging'
export const MESSAGING_PRODUCT_NAME = 'Email & Messaging'

export type MessagingSection =
    | 'overview'
    | 'calendar'
    | 'broadcasts'
    | 'transactional'
    | 'workflows'
    | 'templates'
    | 'channels'
    | 'recipients'
    | 'deliverability'
    | 'settings'

export interface MessagingNavGroup {
    /** A heading, or null for a group that only needs a divider. */
    label: string | null
    sections: MessagingSection[]
}

export const MESSAGING_NAV_GROUPS: MessagingNavGroup[] = [
    { label: null, sections: ['overview', 'calendar'] },
    { label: 'Views', sections: ['broadcasts', 'transactional', 'workflows'] },
    { label: null, sections: ['templates'] },
    { label: 'Setup', sections: ['channels', 'recipients', 'deliverability', 'settings'] },
]

export const MESSAGING_SECTION_LABELS: Record<MessagingSection, string> = {
    overview: 'Overview',
    calendar: 'Calendar',
    broadcasts: 'Broadcasts',
    transactional: 'Transactional emails',
    workflows: 'Messaging workflows',
    templates: 'Templates',
    channels: 'Channels',
    recipients: 'Recipients',
    deliverability: 'Deliverability',
    settings: 'Settings',
}

export const MESSAGING_SECTION_ICONS: Record<MessagingSection, JSX.Element> = {
    overview: <IconHome />,
    calendar: <IconCalendar />,
    broadcasts: <IconSend />,
    transactional: <IconCode />,
    workflows: <IconDecisionTree />,
    templates: <IconDocument />,
    channels: <IconServer />,
    recipients: <IconPeople />,
    deliverability: <IconPulse />,
    settings: <IconGear />,
}

/** Fake counts next to a row, so the sidebar shows what a row would say about its view. */
export const MESSAGING_SECTION_META: Partial<Record<MessagingSection, string>> = {
    calendar: '2 this week',
    broadcasts: '2 scheduled',
    transactional: '4',
    workflows: '5 live',
    channels: '1 to fix',
}

export const MESSAGING_LANDING_SECTION: MessagingSection = 'broadcasts'

export function messagingSectionUrl(section: MessagingSection): string {
    return `${MESSAGING_HOME_PATH}/${section}`
}

export function messagingSectionForPath(pathname: string): MessagingSection | null {
    const path = removeProjectIdIfPresent(pathname)
    if (path !== MESSAGING_HOME_PATH && !path.startsWith(`${MESSAGING_HOME_PATH}/`)) {
        return null
    }
    const segment = path.slice(MESSAGING_HOME_PATH.length + 1).split('/')[0]
    return segment in MESSAGING_SECTION_LABELS ? (segment as MessagingSection) : MESSAGING_LANDING_SECTION
}

export function isMessagingHomePath(pathname: string): boolean {
    return messagingSectionForPath(pathname) !== null
}

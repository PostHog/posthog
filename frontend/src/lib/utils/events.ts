import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { ActionType, EventType } from '~/types'

export function hasTaxonomyPrimaryProperty(eventName: string | null | undefined): boolean {
    return !!eventName && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.primary_property
}

/**
 * Resolves the single property whose value a UI should display alongside an event.
 *
 * Taxonomy-configured defaults (e.g. `$pageview` -> `$pathname`) are immutable and
 * always win; team-configured overrides only apply to events that do not have a
 * taxonomy default.
 *
 * This is a pure client-side lookup — both the taxonomy and the overrides map are
 * already in memory, so callers can invoke this in tight loops (e.g. selectors
 * filtering all events in a session) without n+1 risk.
 */
export function getPrimaryPropertyForEvent(
    eventName: string | null | undefined,
    overrides?: Record<string, string | null | undefined>
): string | null {
    if (!eventName) {
        return null
    }
    const taxonomyDefault = CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventName]?.primary_property
    if (taxonomyDefault) {
        return taxonomyDefault
    }
    return overrides?.[eventName] ?? null
}

/**
 * Filters a list of events down to those that have a primary property
 * (taxonomy default or team override). Pure client-side — wraps
 * `getPrimaryPropertyForEvent` so the intent reads as one operation.
 */
export function getEventsWithPrimaryProperty<T extends { event: string }>(
    events: T[],
    overrides?: Record<string, string | null | undefined>
): T[] {
    return events.filter((e) => getPrimaryPropertyForEvent(e.event, overrides) !== null)
}

/**
 * The distinct set of primary properties promoted for a list of event names
 * (taxonomy default first, then team override). Pure client-side — shared by
 * `taxonomicFilterLogic`'s `eventNamesWithPrimaryProperties` selector and
 * `useTaxonomicGroupsContext`'s headless equivalent so both express
 * "taxonomy default first, then team override, distinct" once.
 */
export function distinctPrimaryPropertiesForEvents(
    eventNames: string[],
    overrides?: Record<string, string | null | undefined>
): string[] {
    const distinct = new Set<string>()
    for (const eventName of eventNames) {
        const primary = getPrimaryPropertyForEvent(eventName, overrides)
        if (primary) {
            distinct.add(primary)
        }
    }
    return Array.from(distinct)
}

export function eventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties'>,
    shortForm: boolean = false
): string {
    if (event.event === '$autocapture') {
        return autoCaptureEventToDescription(event, shortForm)
    }
    // For events with a taxonomy-default primary property (e.g. `$pageview` -> `$pathname`,
    // `$screen` -> `$screen_name`, `$feature_flag_called` -> `$feature_flag`), use the property's
    // value as the description so consumers (notebooks, save-as-action, funnel labels, ...) get
    // useful context instead of the bare event name. Returns the event name when the property
    // isn't present on the event so callers always get something to display.
    const primaryKey = getPrimaryPropertyForEvent(event.event)
    if (primaryKey) {
        const value = event.properties[primaryKey]
        if (value != null && value !== '') {
            return String(value)
        }
    }
    return event.event
}

// $event_type to verb map
export const eventTypeToVerb: { [key: string]: string } = {
    click: 'clicked',
    change: 'changed',
    submit: 'submitted',
    touch: 'touched a',
    value_changed: 'changed value in',
    toggle: 'toggled',
    menu_action: 'pressed menu',
    swipe: 'swiped',
    pinch: 'pinched',
    pan: 'panned',
    rotation: 'rotated',
    long_press: 'long pressed',
    scroll: 'scrolled in',
}

export function autoCaptureEventToDescription(
    event: Pick<EventType, 'elements' | 'event' | 'properties'>,
    shortForm: boolean = false
): string {
    if (event.event !== '$autocapture') {
        return event.event
    }

    const getVerb = (): string => eventTypeToVerb[event.properties.$event_type] || 'interacted with'

    const getTag = (): string => {
        if (event.elements?.[0]?.tag_name === 'a') {
            return 'link'
        } else if (event.elements?.[0]?.tag_name === 'img') {
            return 'image'
        }
        return event.elements?.[0]?.tag_name ?? 'element'
    }

    const getValue = (): string | null => {
        if (event.properties.$el_text) {
            return `${shortForm ? '' : 'with text '}"${event.properties.$el_text}"`
        } else if (event.elements?.[0]?.text) {
            return `${shortForm ? '' : 'with text '}"${event.elements[0].text}"`
        } else if (event.elements?.[0]?.attributes?.['attr__aria-label']) {
            return `${shortForm ? '' : 'with aria label '}"${event.elements[0].attributes['attr__aria-label']}"`
        }
        return null
    }

    if (shortForm) {
        return [getVerb(), getValue() ?? getTag()].filter((x) => x).join(' ')
    }
    const value = getValue()
    return [getVerb(), getTag(), value].filter((x) => x).join(' ')
}

export function getEventNamesForAction(actionId: string | number, allActions: ActionType[]): string[] {
    const id = parseInt(String(actionId))
    return allActions
        .filter((a) => a.id === id)
        .flatMap((a) => a.steps?.filter((step) => step.event).map((step) => String(step.event)) as string[])
}

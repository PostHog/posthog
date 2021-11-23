import { PluginEvent } from '@posthog/plugin-scaffold'
import { Properties } from '@posthog/plugin-scaffold/src/types'
import { captureException } from '@sentry/node'
import escapeStringRegexp from 'escape-string-regexp'
import equal from 'fast-deep-equal'
import { StatsD } from 'hot-shots'
import RE2 from 're2'

import {
    Action,
    ActionStep,
    ActionStepUrlMatching,
    CohortPropertyFilter,
    Element,
    ElementPropertyFilter,
    EventPropertyFilter,
    Person,
    PersonPropertyFilter,
    PropertyFilter,
    PropertyFilterWithOperator,
    PropertyOperator,
} from '../../types'
import { DB } from '../../utils/db/db'
import { extractElements } from '../../utils/db/utils'
import { stringify, stringToBoolean } from '../../utils/utils'
import { ActionManager } from './action-manager'

/** These operators can only be matched if the provided filter's value has the right type. */
const propertyOperatorToRequiredValueType: Partial<Record<PropertyOperator, string[]>> = {
    [PropertyOperator.IContains]: ['string'],
    [PropertyOperator.NotIContains]: ['string'],
    [PropertyOperator.Regex]: ['string'],
    [PropertyOperator.NotRegex]: ['string'],
    [PropertyOperator.GreaterThan]: ['number', 'boolean'],
    [PropertyOperator.LessThan]: ['number', 'boolean'],
}

/** These operators do match when the property is not there, as opposed to normal ones. */
const emptyMatchingOperator: Partial<Record<PropertyOperator, boolean>> = {
    [PropertyOperator.IsNotSet]: true,
    [PropertyOperator.IsNot]: true,
    [PropertyOperator.NotIContains]: true,
    [PropertyOperator.NotRegex]: true,
}

/** Return whether two values compare to each other according to the specified operator.
 * This simulates the behavior of ClickHouse (or other DBMSs) which like to cast values in SELECTs to the column's type.
 */
export function castingCompare(
    a: any, // eslint-disable-line @typescript-eslint/explicit-module-boundary-types
    b: any, // eslint-disable-line @typescript-eslint/explicit-module-boundary-types
    operator: PropertyOperator.Exact | PropertyOperator.IsNot | PropertyOperator.LessThan | PropertyOperator.GreaterThan
): boolean {
    // Check basic case first
    switch (operator) {
        case PropertyOperator.Exact:
            if (a == b) {
                return true
            }
            break
        case PropertyOperator.IsNot:
            if (a != b) {
                return true
            }
            break
        case PropertyOperator.LessThan:
            if (typeof a !== 'string' && typeof b !== 'string' && a < b) {
                return true
            }
            break
        case PropertyOperator.GreaterThan:
            if (typeof a !== 'string' && typeof b !== 'string' && a > b) {
                return true
            }
            break
        default:
            throw new Error(`Operator ${operator} is not supported in castingCompare!`)
    }
    if (typeof a !== typeof b) {
        // Try to cast to number, first via stringToBoolean, and then from raw value if that fails
        const aCast = Number(stringToBoolean(a, true) ?? a)
        const bCast = Number(stringToBoolean(b, true) ?? b)
        // Compare finally (if either cast value is NaN, it will be rejected here too)
        switch (operator) {
            case PropertyOperator.Exact:
                return aCast == bCast
            case PropertyOperator.IsNot:
                return aCast != bCast
            case PropertyOperator.LessThan:
                return aCast < bCast
            case PropertyOperator.GreaterThan:
                return aCast > bCast
        }
    }
    return false
}

export class ActionMatcher {
    private db: DB
    private actionManager: ActionManager
    private statsd: StatsD | undefined

    constructor(db: DB, actionManager: ActionManager, statsd?: StatsD) {
        this.db = db
        this.actionManager = actionManager
        this.statsd = statsd
    }

    /** Get all actions matched to the event. */
    public async match(event: PluginEvent, person?: Person, elements?: Element[]): Promise<Action[]> {
        const matchingStart = new Date()
        const teamActions: Action[] = Object.values(this.actionManager.getTeamActions(event.team_id))
        if (!elements) {
            const rawElements: Record<string, any>[] | undefined = event.properties?.['$elements']
            elements = rawElements ? extractElements(rawElements) : []
        }
        const teamActionsMatching: boolean[] = await Promise.all(
            teamActions.map((action) => this.checkAction(event, elements, person, action))
        )
        const matches: Action[] = []
        for (let i = 0; i < teamActionsMatching.length; i++) {
            if (teamActionsMatching[i]) {
                matches.push(teamActions[i])
            }
        }
        this.statsd?.timing('action_matching_for_event', matchingStart)
        this.statsd?.increment('action_matches_found', matches.length)
        return matches
    }

    /**
     * Base level of action matching.
     *
     * Return whether the event is a match for the action.
     * The event is considered a match if any of the action's steps (match groups) is a match.
     */
    public async checkAction(
        event: PluginEvent,
        elements: Element[] | undefined,
        person: Person | undefined,
        action: Action
    ): Promise<boolean> {
        for (const step of action.steps) {
            try {
                if (await this.checkStep(event, elements, person, step)) {
                    return true
                }
            } catch (error) {
                captureException(error, {
                    tags: { team_id: action.team_id },
                    extra: { event, elements, person, action, step },
                })
            }
        }
        return false
    }

    /**
     * Sublevel 1 of action matching.
     *
     * Return whether the event is a match for the step (match group).
     * The event is considered a match if no subcheck fails. Many subchecks are usually irrelevant and skipped.
     */
    private async checkStep(
        event: PluginEvent,
        elements: Element[] | undefined,
        person: Person | undefined,
        step: ActionStep
    ): Promise<boolean> {
        if (!elements) {
            elements = []
        }
        return (
            this.checkStepElement(elements, step) &&
            this.checkStepUrl(event, step) &&
            this.checkStepEvent(event, step) &&
            (await this.checkStepFilters(event, elements, person, step))
        )
    }

    /**
     * Sublevel 2 of action matching.
     *
     * Return whether the event is a match for the step's "URL" constraint.
     * Step properties: `url_matching`, `url`.
     */
    private checkStepUrl(event: PluginEvent, step: ActionStep): boolean {
        // CHECK CONDITIONS, OTHERWISE SKIPPED
        if (step.url) {
            const eventUrl = event.properties?.$current_url
            if (!eventUrl || typeof eventUrl !== 'string') {
                return false // URL IS UNKNOWN
            }
            let doesUrlMatch: boolean
            switch (step.url_matching) {
                case ActionStepUrlMatching.Regex:
                    // Using RE2 here because that's what ClickHouse uses for regex matching anyway
                    // It's also safer for user-provided patterns because of a few explicit limitations
                    try {
                        doesUrlMatch = new RE2(step.url).test(eventUrl)
                    } catch {
                        doesUrlMatch = false
                    }
                    break
                case ActionStepUrlMatching.Exact:
                    doesUrlMatch = step.url === eventUrl
                    break
                case ActionStepUrlMatching.Contains:
                default:
                    // Simulating SQL LIKE behavior (_ = any single character, % = any zero or more characters)
                    const adjustedRegExpString = escapeStringRegexp(step.url).replace(/_/g, '.').replace(/%/g, '.*')
                    doesUrlMatch = new RegExp(adjustedRegExpString).test(eventUrl)
            }
            if (!doesUrlMatch) {
                return false // URL IS A MISMATCH
            }
        }
        return true
    }

    /**
     * Sublevel 2 of action matching.
     *
     * Return whether the event is a match for
     * the step's "Link href equals", "Text equals" and "HTML selector matches" constraints.
     * Step properties: `tag_name`, `text`, `href`, `selector`.
     */
    private checkStepElement(elements: Element[], step: ActionStep): boolean {
        // CHECK CONDITIONS, OTHERWISE SKIPPED
        if (step.href || step.tag_name || step.text) {
            if (
                !elements.some((element) => {
                    if (step.href && element.href !== step.href) {
                        return false // ELEMENT HREF IS A MISMATCH
                    }
                    if (step.tag_name && element.tag_name !== step.tag_name) {
                        return false // ELEMENT TAG NAME IS A MISMATCH
                    }
                    if (step.text && element.text !== step.text) {
                        return false // ELEMENT TEXT IS A MISMATCH
                    }
                    return true
                })
            ) {
                // AT LEAST ONE ELEMENT MUST BE A SUBMATCH
                return false
            }
        }
        if (step.selector && !this.checkElementsAgainstSelector(elements, step.selector)) {
            return false // SELECTOR IS A MISMATCH
        }
        return true
    }

    /**
     * Sublevel 2 of action matching.
     *
     * Return whether the event is a match for the step's event name constraint.
     * Step property: `event`.
     */
    private checkStepEvent(event: PluginEvent, step: ActionStep): boolean {
        // CHECK CONDITIONS, OTHERWISE SKIPPED
        if (step.event && event.event !== step.event) {
            return false // EVENT NAME IS A MISMATCH
        }
        return true
    }

    /**
     * Sublevel 2 of action matching.
     *
     * Return whether the event is a match for the step's fiter constraints.
     * Step property: `properties`.
     */
    private async checkStepFilters(
        event: PluginEvent,
        elements: Element[],
        person: Person | undefined,
        step: ActionStep
    ): Promise<boolean> {
        // CHECK CONDITIONS, OTHERWISE SKIPPED, OTHERWISE SKIPPED
        if (step.properties && step.properties.length) {
            // EVERY FILTER MUST BE A MATCH
            for (const filter of step.properties) {
                if (!(await this.checkEventAgainstFilter(event, elements, person, filter))) {
                    return false
                }
            }
        }
        return true
    }

    /**
     * Sublevel 3 of action matching.
     */
    private async checkEventAgainstFilter(
        event: PluginEvent,
        elements: Element[],
        person: Person | undefined,
        filter: PropertyFilter
    ): Promise<boolean> {
        switch (filter.type) {
            case 'event':
                return this.checkEventAgainstEventFilter(event, filter)
            case 'person':
                return this.checkEventAgainstPersonFilter(person, filter)
            case 'element':
                return this.checkEventAgainstElementFilter(elements, filter)
            case 'cohort':
                return await this.checkEventAgainstCohortFilter(person, filter)
            default:
                return false
        }
    }

    /**
     * Sublevel 4 of action matching.
     */
    private checkEventAgainstEventFilter(event: PluginEvent, filter: EventPropertyFilter): boolean {
        return this.checkPropertiesAgainstFilter(event.properties, filter)
    }

    /**
     * Sublevel 4 of action matching.
     */
    private checkEventAgainstPersonFilter(person: Person | undefined, filter: PersonPropertyFilter): boolean {
        if (!person?.properties) {
            return !!(filter.operator && emptyMatchingOperator[filter.operator]) // NO PERSON OR PROPERTIES TO MATCH AGAINST FILTER
        }
        return this.checkPropertiesAgainstFilter(person.properties, filter)
    }

    /**
     * Sublevel 4 of action matching.
     */
    private checkEventAgainstElementFilter(elements: Element[], filter: ElementPropertyFilter): boolean {
        if (filter.key === 'selector') {
            const okValues = Array.isArray(filter.value) ? filter.value : [filter.value]
            return okValues.some((okValue) =>
                okValue ? this.checkElementsAgainstSelector(elements, okValue.toString()) : false
            )
        } else {
            return elements.some((element) => this.checkPropertiesAgainstFilter(element, filter))
        }
    }

    /**
     * Sublevel 4 of action matching.
     */
    private async checkEventAgainstCohortFilter(
        person: Person | undefined,
        filter: CohortPropertyFilter
    ): Promise<boolean> {
        let cohortId = filter.value
        if (cohortId === 'all') {
            // The "All users" cohort matches anyone
            return true
        }
        if (!person) {
            return false // NO PERSON TO MATCH AGAINST COHORT
        }
        if (typeof cohortId !== 'number') {
            cohortId = parseInt(cohortId)
        }
        if (isNaN(cohortId)) {
            throw new Error(`Can't match against invalid cohort ID value "${filter.value}!"`)
        }
        return await this.db.doesPersonBelongToCohort(Number(filter.value), person, person.team_id)
    }

    /**
     * Sublevel 5 of action matching.
     */
    private checkPropertiesAgainstFilter(
        properties: Properties | null | undefined,
        filter: PropertyFilterWithOperator
    ): boolean {
        const foundValue = properties?.[filter.key]
        if (foundValue === undefined) {
            return !!(filter.operator && emptyMatchingOperator[filter.operator]) // NO PROPERTIES TO MATCH AGAINST FILTER
        }

        const okValues = Array.isArray(filter.value) ? filter.value : [filter.value]
        let foundValueLowerCase: string // only calculated if needed for a case-insensitive operator

        const requiredValueType = filter.operator && propertyOperatorToRequiredValueType[filter.operator]
        if (requiredValueType && !requiredValueType.includes(typeof foundValue)) {
            return !!(filter.operator && emptyMatchingOperator[filter.operator]) // INCOMPATIBLE WITH OPERATOR SUPPORT
        }

        let test: (okValue: any) => boolean
        switch (filter.operator) {
            case PropertyOperator.IsNot:
                test = (okValue) => castingCompare(foundValue, okValue, PropertyOperator.IsNot)
                break
            case PropertyOperator.IContains:
                foundValueLowerCase = foundValue.toLowerCase()
                test = (okValue) => foundValueLowerCase.includes(stringify(okValue).toLowerCase())
                break
            case PropertyOperator.NotIContains:
                foundValueLowerCase = foundValue.toLowerCase()
                test = (okValue) => !foundValueLowerCase.includes(stringify(okValue).toLowerCase())
                break
            case PropertyOperator.Regex:
                test = (okValue) => new RE2(stringify(okValue)).test(foundValue)
                break
            case PropertyOperator.NotRegex:
                test = (okValue) => !new RE2(stringify(okValue)).test(foundValue)
                break
            case PropertyOperator.GreaterThan:
                test = (okValue) => castingCompare(foundValue, okValue, PropertyOperator.GreaterThan)
                break
            case PropertyOperator.LessThan:
                test = (okValue) => castingCompare(foundValue, okValue, PropertyOperator.LessThan)
                break
            case PropertyOperator.IsSet:
                test = () => foundValue !== undefined
                break
            case PropertyOperator.IsNotSet:
                test = () => foundValue === undefined
                break
            case PropertyOperator.Exact:
            default:
                test = (okValue) => castingCompare(foundValue, okValue, PropertyOperator.Exact)
        }

        return okValues.some(test) // ANY OF POSSIBLE VALUES MUST BE A MATCH AGAINST THE FOUND VALUE
    }

    /**
     * Sublevel 3 or 5 of action matching.
     */
    public checkElementsAgainstSelector(elements: Element[], selector: string, escapeSlashes = true): boolean {
        const parts: SelectorPart[] = []
        // Sometimes people manually add *, just remove them as they don't do anything
        selector = selector
            .replace(/> \* > /g, '')
            .replace(/> \*/g, '')
            .trim()
        const tags = selector.split(' ')
        // Detecting selector parts
        for (let partIndex = 0; partIndex < tags.length; partIndex++) {
            const tag = tags[partIndex]
            if (tag === '>' || tag === '') {
                continue
            }
            const directDescendant = partIndex > 0 && tags[partIndex - 1] === '>'
            const part = new SelectorPart(tag, directDescendant, escapeSlashes)
            part.uniqueOrder = parts.filter((p) => equal(p.requirements, part.requirements)).length
            parts.push(part)
        }
        // Matching elements against selector parts
        // Initial base element is the imaginary parent of the outermost known element
        let baseElementIndex = elements.length
        let wasPartMatched = true
        let partIndex = 0
        while (partIndex < parts.length) {
            if (baseElementIndex <= 0) {
                // At least one part wasn't matched yet, but at the same time there are no more matchable elements left!
                return false
            }
            const part = parts[partIndex]
            wasPartMatched = false
            for (let depthDiff = 1; baseElementIndex - depthDiff >= 0; depthDiff++) {
                // Subtracting depthDiff as elements are reversed, meaning outer elements have higher indexes
                const currentElementIndex = baseElementIndex - depthDiff
                if (
                    this.checkElementAgainstSelectorPartRequirements(elements[currentElementIndex], part.requirements)
                ) {
                    baseElementIndex = currentElementIndex
                    wasPartMatched = true
                    break
                } else if (part.directDescendant) {
                    break
                }
            }
            if (wasPartMatched) {
                partIndex++
            } else {
                if (part.directDescendant) {
                    // For a direct descendant we need to check the parent parent again
                    partIndex--
                } else {
                    // Otherwise we just move the base down
                    baseElementIndex--
                }
            }
        }
        return wasPartMatched
    }

    private checkElementAgainstSelectorPartRequirements(element: Element, requirements: Partial<Element>): boolean {
        if (requirements.text && element.text !== requirements.text) {
            return false
        }
        if (requirements.tag_name && element.tag_name !== requirements.tag_name) {
            return false
        }
        if (requirements.href && element.href !== requirements.href) {
            return false
        }
        if (requirements.attr_id && element.attr_id !== requirements.attr_id) {
            return false
        }
        if (requirements.attr_class) {
            if (
                !element.attr_class?.length ||
                !requirements.attr_class.every((className) => element.attr_class!.includes(className))
            ) {
                return false
            }
        }
        if (requirements.nth_child && element.nth_child !== requirements.nth_child) {
            return false
        }
        if (requirements.nth_of_type && element.nth_of_type !== requirements.nth_of_type) {
            return false
        }
        if (requirements.attributes) {
            const { attributes } = element
            if (!attributes) {
                return false
            }
            for (const [key, value] of Object.entries(requirements.attributes)) {
                if (attributes[`attr__${key}`] !== value) {
                    return false
                }
            }
        }
        return true
    }
}

class SelectorPart {
    directDescendant: boolean
    uniqueOrder: number
    requirements: Partial<Element>

    constructor(tag: string, directDescendant: boolean, escapeSlashes: boolean) {
        const ATTRIBUTE_SELECTOR_REGEX = /\[(.*)=[\'|\"](.*)[\'|\"]\]/
        const COLON_SELECTOR_REGEX = /:([A-Za-z-]+)\((\d+)\)/
        const FINAL_TAG_REGEX = /^([A-Za-z0-9]+)/

        this.directDescendant = directDescendant
        this.uniqueOrder = 0
        this.requirements = {}

        let attributeSelector = tag.match(ATTRIBUTE_SELECTOR_REGEX)
        while (attributeSelector) {
            tag =
                tag.slice(0, attributeSelector.index) +
                tag.slice(attributeSelector.index! + attributeSelector[0].length)
            const attribute = attributeSelector[1].toLowerCase()
            switch (attribute) {
                case 'id':
                    this.requirements.attr_id = attributeSelector[2].toLowerCase()
                    break
                case 'href':
                    this.requirements.href = attributeSelector[2]
                    break
                default:
                    if (!this.requirements.attributes) {
                        this.requirements.attributes = {}
                    }
                    this.requirements.attributes[attribute] = attributeSelector[2]
                    break
            }
            attributeSelector = tag.match(ATTRIBUTE_SELECTOR_REGEX)
        }
        let colonSelector = tag.match(COLON_SELECTOR_REGEX)
        while (colonSelector) {
            tag = tag.slice(0, colonSelector.index) + tag.slice(colonSelector.index! + colonSelector[0].length)
            const parsedArgument = parseInt(colonSelector[2])
            if (!parsedArgument) {
                continue
            }
            switch (colonSelector[1]) {
                case 'nth-child':
                    this.requirements.nth_child = parsedArgument
                    break
                case 'nth-of-type':
                    this.requirements.nth_of_type = parsedArgument
                    break
                default:
                    continue // unsupported selector
            }
            colonSelector = tag.match(COLON_SELECTOR_REGEX)
        }
        if (tag.includes('.')) {
            const classParts = tag.split('.')
            // Strip all slashes that are not followed by another slash
            this.requirements.attr_class = classParts.slice(1)
            if (escapeSlashes) {
                this.requirements.attr_class = this.requirements.attr_class.map(this.unescapeClassName.bind(this))
            } // TODO: determine if we need escapeSlashes in this port
            tag = classParts[0]
        }
        const finalTag = tag.match(FINAL_TAG_REGEX)
        if (finalTag) {
            this.requirements.tag_name = finalTag[1]
        }
    }

    /** Separate all double slashes "\\" (replace them with "\") and remove all single slashes between them. */
    private unescapeClassName(className: string): string {
        return className
            .split('\\\\')
            .map((p) => p.replace(/\\/g, ''))
            .join('\\')
    }
}

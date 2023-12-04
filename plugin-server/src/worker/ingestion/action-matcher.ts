import { Properties } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'
import escapeStringRegexp from 'escape-string-regexp'
import equal from 'fast-deep-equal'
import { StatsD } from 'hot-shots'
import { Summary } from 'prom-client'
import RE2 from 're2'

import {
    Action,
    ActionStep,
    CohortPropertyFilter,
    Element,
    ElementPropertyFilter,
    EventPropertyFilter,
    PersonPropertyFilter,
    PostIngestionEvent,
    PropertyFilter,
    PropertyFilterWithOperator,
    PropertyOperator,
    StringMatching,
} from '../../types'
import { extractElements } from '../../utils/db/elements-chain'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { stringToBoolean } from '../../utils/env-utils'
import { stringify } from '../../utils/utils'
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

const actionMatchMsSummary = new Summary({
    name: 'action_match_ms',
    help: 'Time taken to match actions',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

/** Return whether two values compare to each other according to the specified operator.
 * This simulates the behavior of ClickHouse (or other DBMSs) which like to cast values in SELECTs to the column's type.
 */
export function castingCompare(
    a: any,
    b: any,
    operator: PropertyOperator.Exact | PropertyOperator.IsNot | PropertyOperator.LessThan | PropertyOperator.GreaterThan
): boolean {
    // Do null transformation first
    // Clickhouse treats the string "null" as null, while here we treat them as different values
    // Thus, this check special cases the string "null" to be equal to the null value
    // See more: https://github.com/PostHog/posthog/issues/12893
    if (a === null) {
        a = 'null'
    }
    if (b === null) {
        b = 'null'
    }

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

export function matchString(actual: string, expected: string, matching: StringMatching): boolean {
    switch (matching) {
        case StringMatching.Regex:
            // Using RE2 here because that's what ClickHouse uses for regex matching anyway
            // It's also safer for user-provided patterns because of a few explicit limitations
            try {
                return new RE2(expected).test(actual)
            } catch {
                return false
            }
        case StringMatching.Exact:
            return expected === actual
        case StringMatching.Contains:
            // Simulating SQL LIKE behavior (_ = any single character, % = any zero or more characters)
            const adjustedRegExpString = escapeStringRegexp(expected).replace(/_/g, '.').replace(/%/g, '.*')
            return new RegExp(adjustedRegExpString).test(actual)
    }
}

export class ActionMatcher {
    private postgres: PostgresRouter
    private actionManager: ActionManager
    private statsd: StatsD | undefined

    constructor(postgres: PostgresRouter, actionManager: ActionManager, statsd?: StatsD) {
        this.postgres = postgres
        this.actionManager = actionManager
        this.statsd = statsd
    }

    public hasWebhooks(teamId: number): boolean {
        return Object.keys(this.actionManager.getTeamActions(teamId)).length > 0
    }

    /** Get all actions matched to the event. */
    public async match(event: PostIngestionEvent, elements?: Element[]): Promise<Action[]> {
        const matchingStart = new Date()
        const teamActions: Action[] = Object.values(this.actionManager.getTeamActions(event.teamId))
        if (!elements) {
            const rawElements: Record<string, any>[] | undefined = event.properties?.['$elements']
            elements = rawElements ? extractElements(rawElements) : []
        }
        const teamActionsMatching: boolean[] = await Promise.all(
            teamActions.map((action) => this.checkAction(event, elements, action))
        )
        const matches: Action[] = []
        for (let i = 0; i < teamActionsMatching.length; i++) {
            if (teamActionsMatching[i]) {
                matches.push(teamActions[i])
            }
        }
        this.statsd?.timing('action_matching_for_event', matchingStart)
        this.statsd?.increment('action_matches_found', matches.length)
        actionMatchMsSummary.observe(new Date().getTime() - matchingStart.getTime())
        return matches
    }

    /**
     * Base level of action matching.
     *
     * Return whether the event is a match for the action.
     * The event is considered a match if any of the action's steps (match groups) is a match.
     */
    public async checkAction(
        event: PostIngestionEvent,
        elements: Element[] | undefined,
        action: Action
    ): Promise<boolean> {
        for (const step of action.steps) {
            try {
                if (await this.checkStep(event, elements, step)) {
                    return true
                }
            } catch (error) {
                captureException(error, {
                    tags: { team_id: action.team_id },
                    extra: { event, elements, action, step },
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
        event: PostIngestionEvent,
        elements: Element[] | undefined,
        step: ActionStep
    ): Promise<boolean> {
        if (!elements) {
            elements = []
        }
        return (
            this.checkStepElement(elements, step) &&
            this.checkStepUrl(event, step) &&
            this.checkStepEvent(event, step) &&
            (await this.checkStepFilters(event, elements, step))
        )
    }

    /**
     * Sublevel 2 of action matching.
     *
     * Return whether the event is a match for the step's "URL" constraint.
     * Step properties: `url_matching`, `url`.
     */
    private checkStepUrl(event: PostIngestionEvent, step: ActionStep): boolean {
        // CHECK CONDITIONS, OTHERWISE SKIPPED
        if (step.url) {
            const eventUrl = event.properties?.$current_url
            if (!eventUrl || typeof eventUrl !== 'string') {
                return false // URL IS UNKNOWN
            }
            if (!matchString(eventUrl, step.url, step.url_matching || StringMatching.Contains)) {
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
                    if (
                        step.href &&
                        !matchString(element.href || '', step.href, step.href_matching || StringMatching.Exact)
                    ) {
                        return false // ELEMENT HREF IS A MISMATCH
                    }
                    if (step.tag_name && element.tag_name !== step.tag_name) {
                        return false // ELEMENT TAG NAME IS A MISMATCH
                    }
                    if (
                        step.text &&
                        !matchString(element.text || '', step.text, step.text_matching || StringMatching.Exact)
                    ) {
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
    private checkStepEvent(event: PostIngestionEvent, step: ActionStep): boolean {
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
    private async checkStepFilters(event: PostIngestionEvent, elements: Element[], step: ActionStep): Promise<boolean> {
        // CHECK CONDITIONS, OTHERWISE SKIPPED, OTHERWISE SKIPPED
        if (step.properties && step.properties.length) {
            // EVERY FILTER MUST BE A MATCH
            for (const filter of step.properties) {
                if (!(await this.checkEventAgainstFilter(event, elements, filter))) {
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
        event: PostIngestionEvent,
        elements: Element[],
        filter: PropertyFilter
    ): Promise<boolean> {
        switch (filter.type) {
            case 'event':
                return this.checkEventAgainstEventFilter(event, filter)
            case 'person':
                return this.checkEventAgainstPersonFilter(event.person_properties, filter)
            case 'element':
                return this.checkEventAgainstElementFilter(elements, filter)
            case 'cohort':
                return await this.checkEventAgainstCohortFilter(event.person_id, event.teamId, filter)
            default:
                return false
        }
    }

    /**
     * Sublevel 4 of action matching.
     */
    private checkEventAgainstEventFilter(event: PostIngestionEvent, filter: EventPropertyFilter): boolean {
        return this.checkPropertiesAgainstFilter(event.properties, filter)
    }

    /**
     * Sublevel 4 of action matching.
     */
    private checkEventAgainstPersonFilter(
        personProperties: Properties | undefined,
        filter: PersonPropertyFilter
    ): boolean {
        if (!personProperties) {
            return !!(filter.operator && emptyMatchingOperator[filter.operator]) // NO PERSON OR PROPERTIES TO MATCH AGAINST FILTER
        }
        return this.checkPropertiesAgainstFilter(personProperties, filter)
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
        personUuid: string | undefined,
        teamId: number,
        filter: CohortPropertyFilter
    ): Promise<boolean> {
        let cohortId = filter.value
        if (cohortId === 'all') {
            // The "All users" cohort matches anyone
            return true
        }
        if (!personUuid) {
            return false // NO PERSON TO MATCH AGAINST COHORT
        }
        if (typeof cohortId !== 'number') {
            cohortId = parseInt(cohortId)
        }
        if (isNaN(cohortId)) {
            throw new Error(`Can't match against invalid cohort ID value "${filter.value}!"`)
        }
        return await this.doesPersonBelongToCohort(Number(filter.value), personUuid, teamId)
    }

    public async doesPersonBelongToCohort(cohortId: number, personUuid: string, teamId: number): Promise<boolean> {
        const psqlResult = await this.postgres.query(
            PostgresUse.COMMON_READ,
            `
        SELECT count(1) AS count
        FROM posthog_cohortpeople
        JOIN posthog_cohort ON (posthog_cohort.id = posthog_cohortpeople.cohort_id)
        JOIN (SELECT * FROM posthog_person where team_id = $3) AS posthog_person_in_team ON (posthog_cohortpeople.person_id = posthog_person_in_team.id)
        WHERE cohort_id=$1
          AND posthog_person_in_team.uuid=$2
          AND posthog_cohortpeople.version IS NOT DISTINCT FROM posthog_cohort.version
        `,
            [cohortId, personUuid, teamId],
            'doesPersonBelongToCohort'
        )
        return psqlResult.rows[0].count > 0
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

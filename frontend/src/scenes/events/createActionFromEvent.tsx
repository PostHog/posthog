import { router } from 'kea-router'
import { CLICK_TARGETS, elementToSelector, matchesDataAttribute } from 'lib/actionUtils'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { autoCaptureEventToDescription } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    ActionStepType,
    ActionType,
    ElementPropertyFilter,
    ElementType,
    EventPropertyFilter,
    EventType,
    PropertyFilterType,
    PropertyOperator,
    TeamType,
} from '~/types'

export type MinimalEventFilterType = {
    event: string
    properties: (EventPropertyFilter | ElementPropertyFilter)[]
}

export function recurseSelector(elements: ElementType[], parts: string, index: number): string {
    const element = elements[index]
    if (element.attr_id) {
        return `[id="${element.attr_id}"] > ${parts}`
    }
    if (index > 0) {
        parts = element.tag_name + ' > ' + parts
    } else {
        parts = element.tag_name
    }
    if (index === 10 || !elements[index + 1]) {
        return parts
    }
    return recurseSelector(elements, parts, index + 1)
}

export function elementsToAction(
    elements: ElementType[]
): Pick<ActionStepType, 'selector' | 'text' | 'href' | 'tag_name'> {
    return {
        href: elements[0].href,
        text: elements[0].text,
        ...(!elements[0].href && !elements[0].text ? { selector: recurseSelector(elements, '', 0) } : ''),
    }
}

export async function createActionFromEvent(
    teamId: TeamType['id'],
    event: EventType,
    increment: number,
    dataAttributes: string[],
    recurse: typeof createActionFromEvent = createActionFromEvent
): Promise<void> {
    const actionData: Pick<ActionType, 'name' | 'steps'> = {
        name: '',
        steps: [
            {
                event: event.event,
                ...(event.event === '$pageview' || event.event === '$autocapture'
                    ? {
                          url: event.properties.$current_url,
                          url_matching: 'exact',
                      }
                    : {}),
                ...(event.elements?.length > 0 ? elementsToAction(event.elements) : {}),
            },
        ],
    }
    if (event.event === '$autocapture') {
        actionData.name = autoCaptureEventToDescription(event)
        if (dataAttributes?.length > 0 && event.elements.length > 0) {
            for (let i = 0; i < event.elements.length; i++) {
                const element = event.elements[i]
                if (matchesDataAttribute(element, dataAttributes) || element.attr_id) {
                    let selector = elementToSelector(element, dataAttributes)
                    // we found a data-attr or id, but not on the clicked element.
                    if (i > 0 && !CLICK_TARGETS.includes(element.tag_name)) {
                        const clickedTagName = event.elements[0].tag_name
                        selector = `${selector} > ${clickedTagName || '*'}`
                    }
                    if (actionData.steps?.[0]) {
                        actionData.steps[0].selector = selector
                    }
                    break
                }
            }
        }
    } else if (event.event === '$pageview') {
        actionData.name = `Pageview on ${new URL(event.properties.$current_url).pathname}`
    } else {
        actionData.name = `${event.event} event`
    }
    if (increment) {
        actionData.name = actionData.name + ' ' + increment
    }

    if (event.properties.$event_type === 'submit' && actionData.steps?.length) {
        actionData.steps[0].properties = [
            { key: '$event_type', value: 'submit', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
        ]
    }

    let action: ActionType
    try {
        action = await api.actions.create(actionData)
    } catch (response: any) {
        if (response.type === 'validation_error' && response.code === 'unique' && increment < 30) {
            return recurse(teamId, event, increment + 1, dataAttributes, recurse)
        }
        lemonToast.error(
            <>
                Couldn't create this action. You can try{' '}
                <Link to={urls.createAction()}>manually creating an action instead.</Link>
            </>
        )
        return
    }
    if (action.id) {
        router.actions.push(urls.action(action.id))
        lemonToast.success('Action created')
    }
}

export const createFilterFromEvent = (event: EventType): MinimalEventFilterType => {
    const properties: MinimalEventFilterType['properties'] = []

    if (event.event === '$pageview' || event.event === '$autocapture') {
        properties.push({
            key: '$current_url',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
            value: event.properties?.$current_url || '',
        })
    }

    if (event.event === '$screen') {
        properties.push({
            key: '$screen_name',
            type: PropertyFilterType.Event,
            operator: PropertyOperator.Exact,
            value: event.properties?.$screen_name || '',
        })
    }

    if (event.event === '$autocapture') {
        // THE hard one! - todo...

        if (event.properties.$event_type === 'submit') {
            properties.push({
                key: '$event_type',
                value: 'submit',
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
            })
        }
    }

    return {
        event: event.event,
        properties,
    }
}

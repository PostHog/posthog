import React from 'react'
import { router } from 'kea-router'
import api from 'lib/api'
import { autoCaptureEventToDescription } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { ActionStepType, ActionStepUrlMatching, ActionType, ElementType, EventType, TeamType } from '~/types'
import { CLICK_TARGETS, elementToSelector, matchesDataAttribute } from 'lib/actionUtils'
import { lemonToast } from 'lib/components/lemonToast'
import { urls } from 'scenes/urls'

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
        tag_name: elements[0].tag_name,
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
                          url_matching: ActionStepUrlMatching.Exact,
                      }
                    : {}),
                ...(event.elements.length > 0 ? elementsToAction(event.elements) : {}),
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
        actionData.steps[0].properties = [{ key: '$event_type', value: 'submit' }]
    }

    let action: ActionType
    try {
        action = await api.actions.create(actionData)
    } catch (response: any) {
        if (response.type === 'validation_error' && response.code === 'unique' && increment < 30) {
            return recurse(teamId, event, increment + 1, dataAttributes, recurse)
        } else {
            lemonToast.error(
                <>
                    Couldn't create this action. You can try{' '}
                    <Link to={urls.createAction()}>manually creating an action instead.</Link>
                </>
            )
            return
        }
    }
    if (action.id) {
        router.actions.push(urls.action(action.id))
        lemonToast.success('Action created')
    }
}

import React from 'react'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { eventToName } from 'lib/utils'

export function recurseSelector(elements, parts, index) {
    let element = elements[index]
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

function elementsToAction(elements) {
    return {
        tag_name: elements[0].tag_name,
        href: elements[0].href,
        text: elements[0].text,
        ...(!elements[0].href && !elements[0].text ? { selector: recurseSelector(elements, '', 0) } : ''),
    }
}

export async function createActionFromEvent(event, increment, recurse = createActionFromEvent) {
    let actionData = {
        steps: [
            {
                event: event.event,
                url: event.properties.$current_url,
                url_matching: 'exact',
                ...(event.elements.length > 0 ? elementsToAction(event.elements) : {}),
            },
        ],
    }
    if (event.event === '$autocapture') {
        actionData.name = eventToName(event)
    } else if (event.event === '$pageview') {
        actionData.name = `Pageview on ${new URL(event.properties.$current_url).pathname}`
    } else {
        actionData.name = `${event.event} event`
    }
    if (increment) {
        actionData.name = actionData.name + ' ' + increment
    }

    if (event.properties.$event_type === 'submit') {
        actionData.steps[0].properties = [{ key: '$event_type', value: 'submit' }]
    }

    let action = {}
    try {
        action = await api.create('api/action', actionData)
    } catch (response) {
        if (response.detail === 'action-exists' && increment < 30) {
            return recurse(event, increment + 1, recurse)
        }
    }
    if (action.id) {
        router.actions.push('/action/' + action.id)
        toast(
            <span>
                Action succesfully created.{' '}
                <a
                    href="#"
                    onClick={(e) => {
                        e.preventDefault()
                        window.history.back()
                    }}
                >
                    Click here to go back.
                </a>
            </span>
        )
    }
}

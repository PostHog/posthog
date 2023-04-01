import { JsonType } from 'posthog-js'
import { EventType } from '~/types'

// given a JSON payload which can contain any properties
// replace the parts in curly brackets with the event property values if they exist
// for example:
// payload template = { "message": "{event.name}", "nested_message": "{event.person.property.name.first_name}" }
// event = { "name": "Hello", person: { property: { name: { first_name: "Luke" }}} }
// should give the output { "message": "Hello", "nested_message": "Luke" }

export function applyEventToPayloadTemplate(payloadTemplate: JsonType, event: Partial<EventType>): JsonType {
    function replaceTemplateRecursive(obj: any, path: string[]): any {
        if (typeof obj === 'string') {
            if (obj == '{event}') {
                return event
            }
            const matches = obj.match(/\{event\.[a-zA-Z0-9_.]+\}/g)
            if (matches) {
                for (const match of matches) {
                    const propertyPath = match.slice(7, -1).split('.')
                    let value = event
                    for (const key of propertyPath) {
                        if (value === undefined) {
                            break
                        }
                        value = value[key]
                    }
                    if (value !== undefined) {
                        if (obj === match) {
                            return value
                        } else {
                            obj = obj.replace(match, value)
                        }
                    }
                }
            }
            return obj
        } else if (Array.isArray(obj)) {
            return obj.map((item, index) => replaceTemplateRecursive(item, path.concat(index.toString())))
        } else if (typeof obj === 'object' && obj !== null) {
            const newObj: { [key: string]: any } = {}
            for (const key of Object.keys(obj)) {
                newObj[key] = replaceTemplateRecursive(obj[key], path.concat(key))
            }
            return newObj
        } else {
            return obj
        }
    }

    return replaceTemplateRecursive(payloadTemplate, [])
}

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPlugin,LegacyTransformationPluginMeta } from '../../types'
import metadata from './plugin.json'

type Transformation = {
    matchPattern: RegExp
    transform: (str: string, matchPattern: RegExp) => string
}

const transformations: Record<string, Transformation> = {
    camelCase: {
        matchPattern: /[A-Z]/g,
        transform: (str: string, matchPattern: RegExp) =>
            str[0].toLowerCase() +
            str.slice(1).replace(matchPattern, (substr: string) => substr[substr.length - 1].toUpperCase()),
    },
    PascalCase: {
        matchPattern: /[A-Z]/g,
        transform: (str: string, matchPattern: RegExp) =>
            str[0].toUpperCase() +
            str.slice(1).replace(matchPattern, (substr: string) => substr[substr.length - 1].toUpperCase()),
    },
    snake_case: {
        matchPattern: /([_])([a-z])/g,
        transform: (str: string, matchPattern: RegExp) => defaultTransformation(str, matchPattern, '_'),
    },
    'kebab-case': {
        matchPattern: /([-])([a-z])/g,
        transform: (str: string, matchPattern: RegExp) => defaultTransformation(str, matchPattern, '-'),
    },
    'spaces in between': {
        matchPattern: /([\s])([a-z])/g,
        transform: (str: string, matchPattern: RegExp) => defaultTransformation(str, matchPattern, ' '),
    },
}

const skippedPostHogEvents = ['survey shown', 'survey sent', 'survey dismissed']

export function processEvent(event: PluginEvent, { config }: LegacyTransformationPluginMeta) {
    if (!event.event.startsWith('$') && !skippedPostHogEvents.includes(event.event)) {
        const transformer = transformations[config.defaultNamingConvention]
        event.event = transformer.transform(event.event, transformer.matchPattern)
    }
    return event
}

const defaultTransformation = (str: string, matchPattern: RegExp, sep: string) => {
    const parsedStr = str.replace(
        matchPattern,
        (substr) => sep + (substr.length === 1 ? substr.toLowerCase() : substr[1].toLowerCase())
    )
    if (parsedStr[0] === sep) {
        return parsedStr.slice(1) // Handle PascalCase
    }
    return parsedStr
}

export const taxonomyPlugin: LegacyTransformationPlugin = {
    id: 'taxonomy-plugin',
    metadata: metadata as any,
    processEvent,
}

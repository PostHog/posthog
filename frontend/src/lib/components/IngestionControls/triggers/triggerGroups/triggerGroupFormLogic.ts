import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import { ensureAnchored } from 'lib/components/IngestionControls/triggers/urlConfigLogic'
import { uuid } from 'lib/utils'

import {
    EventTriggerConfig,
    SessionRecordingTriggerGroup,
    TriggerPropertyFilter,
    UrlTriggerConfig,
} from '~/lib/components/IngestionControls/types'

import type { triggerGroupFormLogicType } from './triggerGroupFormLogicType'

function isValidRegex(pattern: string): boolean {
    try {
        new RegExp(pattern)
        return true
    } catch {
        return false
    }
}

/** Normalize stored events to the object format for the form */
function normalizeEvents(events: (string | EventTriggerConfig)[] | undefined): EventTriggerConfig[] {
    return (events || []).map((e) => (typeof e === 'string' ? { name: e } : e))
}

export interface TriggerGroupFormLogicProps {
    group?: SessionRecordingTriggerGroup
    onSave: (group: SessionRecordingTriggerGroup) => void
    onCancel: () => void
}

export const triggerGroupFormLogic = kea<triggerGroupFormLogicType>([
    path(['lib', 'components', 'IngestionControls', 'triggers', 'triggerGroups', 'triggerGroupFormLogic']),
    props({} as TriggerGroupFormLogicProps),
    key((props) => props.group?.id || 'new'),
    actions({
        setIsAddingUrl: (isAdding: boolean) => ({ isAdding }),
        setNewUrl: (url: string) => ({ url }),
        setTestUrl: (url: string) => ({ url }),
        addUrl: (url: string) => ({ url }),
        removeUrl: (url: string) => ({ url }),
        removeEvent: (eventName: string) => ({ eventName }),
        addFlag: (_id: number, key: string) => ({ key }),
        removeFlag: true,
        setEventProperties: (eventName: string, properties: TriggerPropertyFilter[]) => ({ eventName, properties }),
        setExpandedEvent: (eventName: string | null) => ({ eventName }),
    }),
    reducers({
        isAddingUrl: [
            false,
            {
                setIsAddingUrl: (_, { isAdding }) => isAdding,
                addUrl: () => false,
            },
        ],
        newUrl: [
            '',
            {
                setNewUrl: (_, { url }) => url,
                addUrl: () => '',
            },
        ],
        testUrl: [
            '',
            {
                setTestUrl: (_, { url }) => url,
            },
        ],
        expandedEvent: [
            null as string | null,
            {
                setExpandedEvent: (_, { eventName }) => eventName,
            },
        ],
    }),
    forms(({ props }) => ({
        triggerGroup: {
            defaults: {
                name: props.group?.name || '',
                sampleRate: Math.round((props.group?.sampleRate || 1) * 100),
                minDurationMs: props.group?.minDurationMs ?? null,
                matchType: props.group?.conditions.matchType || ('any' as const),
                events: normalizeEvents(props.group?.conditions.events),
                urls: props.group?.conditions.urls || [],
                flag: props.group?.conditions.flag
                    ? typeof props.group.conditions.flag === 'string'
                        ? props.group.conditions.flag
                        : props.group.conditions.flag.key
                    : null,
                properties: props.group?.conditions.properties || [],
            } as {
                name: string
                sampleRate: number
                minDurationMs: number | null
                matchType: 'any' | 'all'
                events: EventTriggerConfig[]
                urls: UrlTriggerConfig[]
                flag: string | null
                properties: TriggerPropertyFilter[]
            },
            errors: ({ name }) => ({
                name: !name?.trim() ? 'Group name is required' : undefined,
            }),
            submit: async (formValues) => {
                const savedGroup: SessionRecordingTriggerGroup = {
                    id: props.group?.id || uuid(),
                    name: formValues.name.trim(),
                    sampleRate: formValues.sampleRate / 100,
                    minDurationMs: formValues.minDurationMs ?? undefined,
                    conditions: {
                        matchType: formValues.matchType,
                        events: formValues.events.length > 0 ? formValues.events : undefined,
                        urls: formValues.urls.length > 0 ? formValues.urls : undefined,
                        flag: formValues.flag || undefined,
                        properties: formValues.properties.length > 0 ? formValues.properties : undefined,
                    },
                }
                props.onSave(savedGroup)
            },
        },
    })),
    listeners(({ actions, values }) => ({
        addUrl: ({ url }) => {
            const trimmedUrl = url.trim()
            if (!trimmedUrl) {
                return
            }

            if (!isValidRegex(trimmedUrl)) {
                lemonToast.error('Invalid regex pattern. Please check your syntax.', { hideButton: true })
                return
            }

            const anchoredUrl = ensureAnchored(trimmedUrl)

            if (values.triggerGroup.urls.find((u) => u.url === anchoredUrl)) {
                lemonToast.warning('This URL pattern has already been added')
                return
            }

            actions.setTriggerGroupValue('urls', [
                ...values.triggerGroup.urls,
                { url: anchoredUrl, matching: 'regex' as const },
            ])
        },
        removeUrl: ({ url }) => {
            actions.setTriggerGroupValue(
                'urls',
                values.triggerGroup.urls.filter((u) => u.url !== url)
            )
        },
        removeEvent: ({ eventName }) => {
            actions.setTriggerGroupValue(
                'events',
                values.triggerGroup.events.filter((e) => e.name !== eventName)
            )
            if (values.expandedEvent === eventName) {
                actions.setExpandedEvent(null)
            }
        },
        addFlag: ({ key }) => {
            actions.setTriggerGroupValue('flag', key)
        },
        removeFlag: () => {
            actions.setTriggerGroupValue('flag', null)
        },
        setEventProperties: ({ eventName, properties }) => {
            actions.setTriggerGroupValue(
                'events',
                values.triggerGroup.events.map((e) => (e.name === eventName ? { ...e, properties } : e))
            )
        },
    })),
])

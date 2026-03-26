import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils'

import { SessionRecordingTriggerGroup, UrlTriggerConfig } from '~/lib/components/IngestionControls/types'

import { replayTriggersV2Logic } from './replayTriggersV2Logic'
import type { triggerGroupFormLogicType } from './triggerGroupFormLogicType'

function isValidRegex(pattern: string): boolean {
    try {
        new RegExp(pattern)
        return true
    } catch {
        return false
    }
}

export interface TriggerGroupFormLogicProps {
    group?: SessionRecordingTriggerGroup
    onSave: (group: SessionRecordingTriggerGroup) => void
    onCancel: () => void
}

export const triggerGroupFormLogic = kea<triggerGroupFormLogicType>([
    path(['scenes', 'settings', 'environment', 'replayTriggers', 'triggerGroupFormLogic']),
    props({} as TriggerGroupFormLogicProps),
    key((props) => props.group?.id || 'new'),
    connect({
        values: [replayTriggersV2Logic, ['triggerGroups']],
    }),
    actions({
        setIsAddingUrl: (isAdding: boolean) => ({ isAdding }),
        setNewUrl: (url: string) => ({ url }),
        setTestUrl: (url: string) => ({ url }),
        addUrl: true,
        removeUrl: (url: string) => ({ url }),
        removeEvent: (event: string) => ({ event }),
        addFlag: (_id: number, key: string) => ({ key }),
        removeFlag: true,
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
    }),
    forms(({ props }) => ({
        triggerGroup: {
            defaults: {
                name: props.group?.name || '',
                sampleRate: Math.round((props.group?.sampleRate || 1) * 100),
                minDurationMs: props.group?.minDurationMs ?? null,
                matchType: props.group?.conditions.matchType || ('any' as const),
                events: props.group?.conditions.events || [],
                urls: props.group?.conditions.urls || [],
                flag: props.group?.conditions.flag
                    ? typeof props.group.conditions.flag === 'string'
                        ? props.group.conditions.flag
                        : props.group.conditions.flag.key
                    : null,
            } as {
                name: string
                sampleRate: number
                minDurationMs: number | null
                matchType: 'any' | 'all'
                events: string[]
                urls: UrlTriggerConfig[]
                flag: string | null
            },
            errors: ({ name, urls }) => ({
                name: !name?.trim() ? 'Group name is required' : undefined,
                urls: urls.some((urlConfig) => !isValidRegex(urlConfig.url))
                    ? 'One or more URL patterns are invalid'
                    : undefined,
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
                    },
                }
                props.onSave(savedGroup)
            },
        },
    })),
    selectors({
        isEditing: [(_, p) => [p.group], (group): boolean => !!group],
    }),
    listeners(({ actions, values }) => ({
        addUrl: () => {
            const trimmedUrl = values.newUrl.trim()
            if (!trimmedUrl) {
                return
            }

            // Validate regex pattern
            if (!isValidRegex(trimmedUrl)) {
                lemonToast.error('Invalid regex pattern. Please check your syntax.')
                return
            }

            // Check for duplicates
            if (values.triggerGroup.urls.find((u) => u.url === trimmedUrl)) {
                lemonToast.warning('This URL pattern has already been added')
                return
            }

            actions.setTriggerGroupValue('urls', [
                ...values.triggerGroup.urls,
                { url: trimmedUrl, matching: 'regex' as const },
            ])
        },
        removeUrl: ({ url }) => {
            actions.setTriggerGroupValue(
                'urls',
                values.triggerGroup.urls.filter((u) => u.url !== url)
            )
        },
        removeEvent: ({ event }) => {
            actions.setTriggerGroupValue(
                'events',
                values.triggerGroup.events.filter((e) => e !== event)
            )
        },
        addFlag: ({ key }) => {
            actions.setTriggerGroupValue('flag', key)
        },
        removeFlag: () => {
            actions.setTriggerGroupValue('flag', null)
        },
    })),
])

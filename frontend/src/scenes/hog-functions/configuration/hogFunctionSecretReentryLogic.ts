import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import type { FieldName } from 'kea-forms'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { MASKED_SECRET_VALUE, secretEntries } from 'lib/components/CyclotronJob/dictionarySecretRows'
import { SecretReentryRefusal, parseSecretReentryRefusal } from 'lib/utils/secretReentryRefusal'

import type { CyclotronJobInputType, HogFunctionConfigurationType } from '~/types'

import type {
    HogFunctionPublishRequestApiInputs,
    HogFunctionPublishSecretInputApiValue,
} from 'products/cdp/frontend/generated/api.schemas'

import {
    HogFunctionConfigurationLogicProps,
    hogFunctionConfigurationLogic,
    hogFunctionConfigurationLogicKey,
} from './hogFunctionConfigurationLogic'

export type SecretReentrySource = 'save' | 'test' | 'publish'

export type SecretReentryConfiguration = Pick<Partial<HogFunctionConfigurationType>, 'inputs_schema' | 'inputs'>

export type EnteredSecretInputs = HogFunctionPublishRequestApiInputs

export interface SecretReentryField {
    key: string
    label: string
    entryKeys: string[] | null
}

export interface SecretReentryPrompt {
    // Every stored secret the request still sends as "keep the stored value". A save or test run needs all of
    // them. Publish also accepts a secret a draft edit typed, but the draft masks every secret alike, so it asks for all.
    secrets: SecretReentryField[]
    source: SecretReentrySource
}

interface SecretReentryCache {
    onContinue?: (entered: EnteredSecretInputs) => void
    configuration?: SecretReentryConfiguration | null
    markedInputKeys?: Set<string>
}

export function withEnteredSecrets<T extends SecretReentryConfiguration>(
    configuration: T,
    entered: EnteredSecretInputs | undefined
): T {
    if (!entered) {
        return configuration
    }
    const inputs = { ...configuration.inputs }
    for (const [key, { value }] of Object.entries(entered)) {
        // A `secret` input means "keep the stored value", so the entered one drops the flag. The masked input
        // carries the stored templating, so the entered value runs with it.
        inputs[key] = { ...inputs[key], secret: false, value }
    }
    return { ...configuration, inputs }
}

function textEntries(input: CyclotronJobInputType | undefined): Record<string, string> {
    return Object.fromEntries(
        Object.entries(secretEntries(input) ?? {}).filter(
            (entry): entry is [string, string] => typeof entry[1] === 'string'
        )
    )
}

// Like the backend, which needs no blank secret entered again, because it holds nothing the code could send.
function isBlankSecret(input: CyclotronJobInputType | undefined): boolean {
    const entries = secretEntries(input)
    return input?.value === '' || (!!entries && Object.keys(entries).length === 0)
}

// The dialog types text, so it can ask for a secret stored as text or as a dictionary that lists its masked keys.
// Any other stored secret is returned as unaskable, and the request can then only be fixed in the form.
function storedSecrets(configuration: SecretReentryConfiguration): {
    fields: SecretReentryField[]
    unaskable: SecretReentryField[]
} {
    const fields: SecretReentryField[] = []
    const unaskable: SecretReentryField[] = []
    for (const schema of configuration.inputs_schema ?? []) {
        const input = configuration.inputs?.[schema.key]
        if (!schema.secret || isBlankSecret(input)) {
            continue
        }
        const field = { key: schema.key, label: schema.label || schema.key, entryKeys: null }
        if (schema.type === 'dictionary') {
            const entries = textEntries(input)
            const entryKeys = Object.keys(entries).filter((entry) => entries[entry] === MASKED_SECRET_VALUE)
            if (entryKeys.length) {
                fields.push({ ...field, entryKeys })
                continue
            }
        } else if (schema.type === 'string' && input?.secret) {
            fields.push(field)
            continue
        }
        if (input?.secret) {
            unaskable.push(field)
        }
    }
    return { fields, unaskable }
}

function changedInputKey(name: FieldName): string | null {
    const path = Array.isArray(name) ? name : String(name).split('.')
    return path[0] === 'inputs' && path.length > 1 ? String(path[1]) : null
}

function unavailableMessage(label: string, source: SecretReentrySource): string {
    return source === 'publish'
        ? `The staged changes need ${label} entered again, which isn't possible here. Discard the draft and make the change in the form.`
        : `Enter ${label} again in the form. Changes to the code, inputs or mappings need every stored secret entered again.`
}

function trackingProperties(prompt: SecretReentryPrompt): Record<string, string | number> {
    return { source: prompt.source, secret_count: prompt.secrets.length }
}

function enteredValue(
    field: SecretReentryField,
    input: CyclotronJobInputType | undefined,
    secretValues: Record<string, string>,
    secretEntryValues: Record<string, Record<string, string>>
): HogFunctionPublishSecretInputApiValue {
    return field.entryKeys ? { ...textEntries(input), ...secretEntryValues[field.key] } : secretValues[field.key]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFunctionSecretReentryLogicValues {
    configuration: HogFunctionConfigurationType // hogFunctionConfigurationLogic
    configurationManualErrors: Record<string, any> // hogFunctionConfigurationLogic
    confirmDisabledReason: string | undefined
    isOpen: boolean
    prompt: SecretReentryPrompt | null
    secretEntryValues: Record<string, Record<string, string>>
    secretValues: Record<string, string>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFunctionSecretReentryLogicActions {
    setConfigurationManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    } // hogFunctionConfigurationLogic
    setConfigurationValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    } // hogFunctionConfigurationLogic
    submitConfigurationRequest: (configuration: HogFunctionConfigurationType) => {
        configuration: HogFunctionConfigurationType
    } // hogFunctionConfigurationLogic
    upsertHogFunctionFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // hogFunctionConfigurationLogic
    cancelSecretReentry: () => {
        value: true
    }
    clearSecretReentry: () => {
        value: true
    }
    closeSecretReentry: () => {
        value: true
    }
    confirmSecretReentry: () => {
        value: true
    }
    openSecretReentry: (prompt: SecretReentryPrompt) => {
        prompt: SecretReentryPrompt
    }
    requireSecretReentry: (
        refusal: SecretReentryRefusal,
        source: SecretReentrySource,
        onContinue: (entered: EnteredSecretInputs) => void,
        configuration?: SecretReentryConfiguration | null
    ) => {
        configuration: SecretReentryConfiguration | null | undefined
        onContinue: (entered: EnteredSecretInputs) => void
        refusal: SecretReentryRefusal
        source: SecretReentrySource
    }
    setSecretEntry: (
        key: string,
        entryKey: string,
        value: string
    ) => {
        entryKey: string
        key: string
        value: string
    }
    setSecretValue: (
        key: string,
        value: string
    ) => {
        key: string
        value: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface hogFunctionSecretReentryLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        confirmDisabledReason: (
            prompt: SecretReentryPrompt | null,
            secretValues: Record<string, string>,
            secretEntryValues: Record<string, Record<string, string>>
        ) => string | undefined
    }
}

export type hogFunctionSecretReentryLogicType = MakeLogicType<
    hogFunctionSecretReentryLogicValues,
    hogFunctionSecretReentryLogicActions,
    HogFunctionConfigurationLogicProps,
    hogFunctionSecretReentryLogicMeta
>

export const hogFunctionSecretReentryLogic = kea<hogFunctionSecretReentryLogicType>([
    props({} as HogFunctionConfigurationLogicProps),
    key(hogFunctionConfigurationLogicKey),
    path((key) => ['scenes', 'hog-functions', 'configuration', 'hogFunctionSecretReentryLogic', key]),
    connect((props: HogFunctionConfigurationLogicProps) => ({
        values: [hogFunctionConfigurationLogic(props), ['configuration', 'configurationManualErrors']],
        actions: [
            hogFunctionConfigurationLogic(props),
            [
                'setConfigurationValue',
                'setConfigurationManualErrors',
                'submitConfigurationRequest',
                'upsertHogFunctionFailure',
            ],
        ],
    })),
    actions({
        // `configuration` is what the refused request sent, when that is not the form: the staged draft for publish.
        requireSecretReentry: (
            refusal: SecretReentryRefusal,
            source: SecretReentrySource,
            onContinue: (entered: EnteredSecretInputs) => void,
            configuration?: SecretReentryConfiguration | null
        ) => ({ refusal, source, onContinue, configuration }),
        openSecretReentry: (prompt: SecretReentryPrompt) => ({ prompt }),
        setSecretValue: (key: string, value: string) => ({ key, value }),
        setSecretEntry: (key: string, entryKey: string, value: string) => ({ key, entryKey, value }),
        cancelSecretReentry: true,
        confirmSecretReentry: true,
        closeSecretReentry: true,
        clearSecretReentry: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openSecretReentry: () => true,
                closeSecretReentry: () => false,
            },
        ],
        // Kept after close until the modal has animated out, so the closing dialog does not change its content.
        prompt: [
            null as SecretReentryPrompt | null,
            {
                openSecretReentry: (_, { prompt }) => prompt,
                clearSecretReentry: () => null,
            },
        ],
        secretValues: [
            {} as Record<string, string>,
            {
                setSecretValue: (state, { key, value }) => ({ ...state, [key]: value }),
                openSecretReentry: () => ({}),
                clearSecretReentry: () => ({}),
            },
        ],
        secretEntryValues: [
            {} as Record<string, Record<string, string>>,
            {
                setSecretEntry: (state, { key, entryKey, value }) => ({
                    ...state,
                    [key]: { ...state[key], [entryKey]: value },
                }),
                openSecretReentry: () => ({}),
                clearSecretReentry: () => ({}),
            },
        ],
    }),
    selectors({
        confirmDisabledReason: [
            (s) => [s.prompt, s.secretValues, s.secretEntryValues],
            (
                prompt: SecretReentryPrompt | null,
                secretValues: Record<string, string>,
                secretEntryValues: Record<string, Record<string, string>>
            ): string | undefined => {
                const complete = prompt?.secrets.every(({ key, entryKeys }) =>
                    entryKeys
                        ? entryKeys.every((entry) => secretEntryValues[key]?.[entry]?.trim())
                        : secretValues[key]?.trim()
                )
                return !prompt || complete ? undefined : 'Enter every secret'
            },
        ],
    }),
    listeners(({ actions, values, cache: logicCache }) => {
        const cache: SecretReentryCache = logicCache
        return {
            upsertHogFunctionFailure: ({ errorObject }) => {
                const refusal = parseSecretReentryRefusal(errorObject)
                if (refusal) {
                    // The retry skips the form's own submit, which would send the form without the entered secrets.
                    actions.requireSecretReentry(refusal, 'save', (entered) =>
                        actions.submitConfigurationRequest(withEnteredSecrets(values.configuration, entered))
                    )
                }
            },
            setConfigurationValue: ({ name }) => {
                // The form clears manual errors only after a failed save, and a refused test run is not one.
                const key = changedInputKey(name)
                const inputErrors = values.configurationManualErrors.inputs
                if (!key || !cache.markedInputKeys?.has(key) || !inputErrors?.[key]) {
                    return
                }
                cache.markedInputKeys.delete(key)
                const { [key]: _cleared, ...otherInputErrors } = inputErrors
                actions.setConfigurationManualErrors({ ...values.configurationManualErrors, inputs: otherInputErrors })
            },
            requireSecretReentry: ({ refusal, source, onContinue, configuration }) => {
                const asked = configuration ?? values.configuration
                const { fields, unaskable } = storedSecrets(asked)
                if (unaskable.length || !fields.some((field) => field.key === refusal.key)) {
                    // pinned: analytics event name - renaming breaks dashboards
                    posthog.capture('hog function secret reentry unavailable', { source })
                    const refusedSchema = asked.inputs_schema?.find((s) => s.key === refusal.key)
                    const marked = unaskable.length ? unaskable : refusedSchema ? [refusal] : []
                    const label = unaskable[0]?.label ?? (refusedSchema?.label || refusal.key)
                    lemonToast.error(unavailableMessage(label, source))
                    if (marked.length && source !== 'publish') {
                        const manualErrors = values.configurationManualErrors
                        cache.markedInputKeys = new Set(marked.map(({ key }) => key))
                        actions.setConfigurationManualErrors({
                            ...manualErrors,
                            inputs: {
                                ...manualErrors.inputs,
                                ...Object.fromEntries(marked.map(({ key }) => [key, refusal.detail])),
                            },
                        })
                    }
                    return
                }
                cache.onContinue = onContinue
                cache.configuration = configuration
                const prompt = { secrets: fields, source }
                actions.openSecretReentry(prompt)
                // pinned: analytics event name - renaming breaks dashboards
                posthog.capture('hog function secret reentry shown', trackingProperties(prompt))
            },
            cancelSecretReentry: () => {
                if (values.prompt) {
                    // pinned: analytics event name - renaming breaks dashboards
                    posthog.capture('hog function secret reentry cancelled', trackingProperties(values.prompt))
                }
                // The retry closure can hold secrets typed in an earlier round, so it goes with the dialog.
                cache.onContinue = undefined
                cache.configuration = undefined
                actions.closeSecretReentry()
            },
            confirmSecretReentry: () => {
                const { prompt, secretValues, secretEntryValues } = values
                if (!values.isOpen || !prompt || values.confirmDisabledReason) {
                    return
                }
                const configuration = cache.configuration ?? values.configuration
                const entered: EnteredSecretInputs = Object.fromEntries(
                    prompt.secrets.map((field) => [
                        field.key,
                        {
                            value: enteredValue(
                                field,
                                configuration.inputs?.[field.key],
                                secretValues,
                                secretEntryValues
                            ),
                        },
                    ])
                )
                // pinned: analytics event name - renaming breaks dashboards
                posthog.capture('hog function secret reentry confirmed', trackingProperties(prompt))
                const onContinue = cache.onContinue
                cache.onContinue = undefined
                cache.configuration = undefined
                actions.closeSecretReentry()
                onContinue?.(entered)
            },
        }
    }),
])

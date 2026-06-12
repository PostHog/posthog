import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { HealthIssueKind, KIND_LABELS } from 'scenes/health/healthCategories'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import {
    CyclotronJobFiltersType,
    CyclotronJobInputType,
    HogFunctionSubTemplateIdType,
    HogFunctionTemplateType,
    HogFunctionType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { alertWizardLogicType } from './alertWizardLogicType'

export enum WizardStep {
    Destination = 'destination',
    Trigger = 'trigger',
    Configure = 'configure',
}

export enum AlertCreationView {
    None = 'none',
    Wizard = 'wizard',
    Traditional = 'traditional',
}

export interface WizardDestination {
    key: string
    name: string
    description: string
    icon: string
    templateId: string
}

export interface WizardTrigger {
    key: HogFunctionSubTemplateIdType
    name: string
    description: string
}

export interface AlertWizardLogicProps {
    logicKey: string
    subTemplateIds: HogFunctionSubTemplateIdType[]
    triggers: WizardTrigger[]
    destinations: WizardDestination[]
    disableUrlSync?: boolean
    presetTriggerKey?: HogFunctionSubTemplateIdType
    // When set, the wizard pre-applies a `kind IN (...)` property filter on the
    // first event of the created HogFunction. Used by the health-alerts family
    // so a per-page entry point (e.g. the SDK Health scene) can scope the alert
    // to one or more health-check kinds. Pass an empty array to mean "all kinds"
    // explicitly; omit the prop to leave filters untouched.
    presetTriggerKinds?: string[]
    onAlertCreated?: () => void
}

const PRIMARY_DESTINATION_LIMIT = 3

function hasSubTemplateForDestination(
    triggerKey: HogFunctionSubTemplateIdType,
    destination: WizardDestination
): boolean {
    const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[triggerKey]
    return subTemplates?.some((t) => t.template_id === destination.templateId) ?? false
}

// Pre-applies `kind IN (selectedKinds)` as a top-level property filter on the
// sub-template's filter group. A null or empty `selectedKinds` leaves filters
// untouched (matches every kind). Used by the health-alerts family so a per-page
// entry point can scope the resulting HogFunction to specific kinds.
//
// Top-level (vs `events[0].properties`) matches the convention of the trigger
// UI in HogFunctionFiltersInternal, so the kind filter remains visible and
// editable on the new-function page, and survives a trigger change (which
// rewrites `events`).
export function applyKindFilter(
    baseFilters: CyclotronJobFiltersType | null | undefined,
    selectedKinds: string[] | null
): CyclotronJobFiltersType | null | undefined {
    if (!baseFilters || !selectedKinds || selectedKinds.length === 0) {
        return baseFilters
    }
    return {
        ...baseFilters,
        properties: [
            {
                key: 'kind',
                value: selectedKinds,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
    }
}

// Renders a selectedKinds list as a short, human-readable parenthetical suffix
// (e.g. "(SDK outdated)" or "(SDK outdated, External data failures)") that can
// be appended to a sub-template's generic name/description, so the created
// HogFunction is immediately identifiable in lists.
function formatKindsSuffix(selectedKinds: string[] | null | undefined): string {
    if (!selectedKinds || selectedKinds.length === 0) {
        return ''
    }
    const labels = selectedKinds.map((k) => KIND_LABELS[k as HealthIssueKind] ?? k)
    return ` (${labels.join(', ')})`
}

export function decorateAlertName(baseName: string, selectedKinds: string[] | null | undefined): string {
    return `${baseName}${formatKindsSuffix(selectedKinds)}`
}

function extractDestinationKeyFromAlert(alert: HogFunctionType, allDestinations: WizardDestination[]): string | null {
    const templateId = alert.template?.id
    if (!templateId) {
        return null
    }
    for (const destination of allDestinations) {
        if (templateId.startsWith(destination.templateId)) {
            return destination.key
        }
    }
    return null
}

export const alertWizardLogic = kea<alertWizardLogicType>([
    props({} as AlertWizardLogicProps),
    key((p) => p.logicKey),
    path((key) => ['scenes', 'hog-functions', 'AlertWizard', 'alertWizardLogic', key]),

    actions({
        setAlertCreationView: (view: AlertCreationView) => ({ view }),
        setStep: (step: WizardStep) => ({ step }),
        setDestinationKey: (destinationKey: string) => ({ destinationKey }),
        setTriggerKey: (triggerKey: HogFunctionSubTemplateIdType) => ({ triggerKey }),
        setInputValue: (key: string, value: CyclotronJobInputType) => ({ key, value }),
        restoreWizardState: (state: {
            step: WizardStep
            destinationKey: string | null
            triggerKey: HogFunctionSubTemplateIdType | null
        }) => ({ state }),
        resetWizard: true,
        createAlertSuccess: true,
        submitConfiguration: true,
        submitConfigurationComplete: true,
        testConfiguration: true,
        testConfigurationComplete: true,
    }),

    reducers(({ props: logicProps }) => ({
        subTemplateIds: [logicProps.subTemplateIds, {}],
        triggers: [logicProps.triggers as WizardTrigger[], {}],
        allDestinations: [logicProps.destinations as WizardDestination[], {}],
        alertCreationView: [
            AlertCreationView.None as AlertCreationView,
            {
                setAlertCreationView: (_, { view }) => view,
                restoreWizardState: () => AlertCreationView.Wizard as AlertCreationView,
                createAlertSuccess: () => AlertCreationView.None as AlertCreationView,
            },
        ],
        currentStep: [
            WizardStep.Destination as WizardStep,
            {
                setStep: (_, { step }) => step,
                setDestinationKey: () =>
                    (logicProps.presetTriggerKey ? WizardStep.Configure : WizardStep.Trigger) as WizardStep,
                restoreWizardState: (_, { state }) => state.step,
                resetWizard: () => WizardStep.Destination as WizardStep,
            },
        ],
        selectedDestinationKey: [
            null as string | null,
            {
                setDestinationKey: (_, { destinationKey }) => destinationKey,
                restoreWizardState: (_, { state }) => state.destinationKey,
                resetWizard: () => null,
            },
        ],
        selectedTriggerKey: [
            (logicProps.presetTriggerKey ?? null) as HogFunctionSubTemplateIdType | null,
            {
                setTriggerKey: (_, { triggerKey }) => triggerKey,
                restoreWizardState: (_, { state }) => state.triggerKey,
                resetWizard: () => (logicProps.presetTriggerKey ?? null) as HogFunctionSubTemplateIdType | null,
            },
        ],
        selectedKinds: [
            (logicProps.presetTriggerKinds ?? null) as string[] | null,
            {
                resetWizard: () => (logicProps.presetTriggerKinds ?? null) as string[] | null,
            },
        ],
        alertCreated: [
            false,
            {
                createAlertSuccess: () => true,
                resetWizard: () => false,
            },
        ],
        inputValues: [
            {} as Record<string, CyclotronJobInputType>,
            {
                setInputValue: (state, { key, value }) => ({ ...state, [key]: value }),
                resetWizard: () => ({}),
                setDestinationKey: () => ({}),
                setTriggerKey: () => ({}),
            },
        ],
        submitting: [
            false,
            {
                submitConfiguration: () => true,
                submitConfigurationComplete: () => false,
                createAlertSuccess: () => false,
            },
        ],
        testing: [
            false,
            {
                testConfiguration: () => true,
                testConfigurationComplete: () => false,
            },
        ],
    })),

    loaders(({ props: logicProps }) => ({
        existingAlerts: [
            [] as HogFunctionType[],
            {
                loadExistingAlerts: async () => {
                    const filters = logicProps.subTemplateIds
                        .map((id) => HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[id]?.filters)
                        .filter(Boolean)

                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: filters as any[],
                        limit: 100,
                    })

                    return response.results
                },
            },
        ],
        selectedTemplate: [
            null as HogFunctionTemplateType | null,
            {
                loadTemplate: async (templateId: string) => {
                    return await api.hogFunctions.getTemplate(templateId)
                },
            },
        ],
    })),

    selectors({
        usedDestinationKeys: [
            (s) => [s.existingAlerts, s.allDestinations],
            (existingAlerts, allDestinations): Set<string> => {
                const used = new Set<string>()
                for (const alert of existingAlerts) {
                    const key = extractDestinationKeyFromAlert(alert, allDestinations)
                    if (key) {
                        used.add(key)
                    }
                }
                return used
            },
        ],

        sortedDestinations: [
            (s) => [s.usedDestinationKeys, s.allDestinations],
            (usedDestinationKeys, allDestinations): WizardDestination[] => {
                return [...allDestinations].sort((a, b) => {
                    const aUsed = usedDestinationKeys.has(a.key) ? 1 : 0
                    const bUsed = usedDestinationKeys.has(b.key) ? 1 : 0
                    return bUsed - aUsed
                })
            },
        ],

        primaryDestinations: [
            (s) => [s.sortedDestinations],
            (sortedDestinations): WizardDestination[] => sortedDestinations.slice(0, PRIMARY_DESTINATION_LIMIT),
        ],

        extraDestinations: [
            (s) => [s.sortedDestinations],
            (sortedDestinations): WizardDestination[] => sortedDestinations.slice(PRIMARY_DESTINATION_LIMIT),
        ],

        availableTriggers: [
            (s) => [s.selectedDestinationKey, s.triggers, s.allDestinations],
            (selectedDestinationKey, triggers, allDestinations): WizardTrigger[] => {
                if (!selectedDestinationKey) {
                    return triggers
                }
                const destination = allDestinations.find((d) => d.key === selectedDestinationKey)
                if (!destination) {
                    return triggers
                }
                return triggers.filter((trigger) => hasSubTemplateForDestination(trigger.key, destination))
            },
        ],

        activeSubTemplate: [
            (s) => [s.selectedDestinationKey, s.selectedTriggerKey, s.allDestinations],
            (selectedDestinationKey, selectedTriggerKey, allDestinations) => {
                if (!selectedDestinationKey || !selectedTriggerKey) {
                    return null
                }
                const destination = allDestinations.find((d) => d.key === selectedDestinationKey)
                if (!destination) {
                    return null
                }
                const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[selectedTriggerKey]
                return subTemplates?.find((t) => t.template_id === destination.templateId) ?? null
            },
        ],

        requiredInputsSchema: [
            (s) => [s.selectedTemplate, s.activeSubTemplate],
            (selectedTemplate, activeSubTemplate) => {
                if (!selectedTemplate) {
                    return []
                }
                const prefilledKeys = new Set(Object.keys(activeSubTemplate?.inputs ?? {}))
                return (selectedTemplate.inputs_schema ?? []).filter(
                    (s) =>
                        s.required &&
                        !prefilledKeys.has(s.key) &&
                        (s.type === 'integration' || s.type === 'integration_field' || s.type === 'string')
                )
            },
        ],

        configuration: [
            (s) => [s.selectedTemplate, s.inputValues],
            (selectedTemplate, inputValues) => ({
                inputs_schema: selectedTemplate?.inputs_schema ?? [],
                inputs: inputValues,
            }),
        ],
    }),

    listeners(({ values, actions, props: logicProps }) => ({
        createAlertSuccess: () => {
            actions.resetWizard()
            actions.loadExistingAlerts()
            logicProps.onAlertCreated?.()
        },

        setAlertCreationView: ({ view }) => {
            if (view === AlertCreationView.Wizard) {
                actions.loadExistingAlerts()
            }
        },

        restoreWizardState: ({ state }) => {
            if (state.destinationKey && state.triggerKey) {
                const destination = values.allDestinations.find((d) => d.key === state.destinationKey)
                if (destination) {
                    actions.loadTemplate(destination.templateId)
                }
            }
            actions.loadExistingAlerts()
        },

        setTriggerKey: () => {
            const destinationKey = values.selectedDestinationKey
            if (destinationKey) {
                const destination = values.allDestinations.find((d) => d.key === destinationKey)!
                actions.loadTemplate(destination.templateId)
            }
            actions.setStep(WizardStep.Configure)
        },

        setDestinationKey: ({ destinationKey }) => {
            if (logicProps.presetTriggerKey) {
                const destination = values.allDestinations.find((d) => d.key === destinationKey)
                if (destination) {
                    actions.loadTemplate(destination.templateId)
                }
            }
        },

        testConfiguration: async (_, breakpoint) => {
            const destinationKey = values.selectedDestinationKey
            const triggerKey = values.selectedTriggerKey

            if (!destinationKey || !triggerKey) {
                return
            }

            const destination = values.allDestinations.find((d) => d.key === destinationKey)!
            const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[triggerKey]
            const subTemplate = subTemplates.find((t) => t.template_id === destination.templateId)

            if (!subTemplate) {
                lemonToast.error('Template not found for this combination')
                return
            }

            const mergedInputs: Record<string, any> = { ...subTemplate.inputs }
            for (const [key, val] of Object.entries(values.inputValues)) {
                mergedInputs[key] = val
            }

            const selectedTemplate = values.selectedTemplate
            if (!selectedTemplate) {
                lemonToast.error('Template not loaded yet')
                actions.testConfigurationComplete()
                return
            }

            const configuration: Record<string, any> = {
                type: 'internal_destination',
                template_id: destination.templateId,
                filters: subTemplate.filters,
                enabled: true,
                masking: null,
                inputs: mergedInputs,
                inputs_schema: selectedTemplate.inputs_schema,
                hog: selectedTemplate.code,
            }

            const globals = {
                event: {
                    uuid: 'test-event-uuid',
                    distinct_id: 'test-distinct-id',
                    timestamp: new Date().toISOString(),
                    event: subTemplate.filters?.events?.[0]?.id || triggerKey,
                    properties: {
                        name: 'Test issue',
                        description: 'This is a test alert from PostHog',
                    },
                },
                project: {
                    id: 0,
                    name: 'Test project',
                    url: window.location.origin,
                },
                source: {
                    name: 'Alert wizard',
                    url: window.location.href,
                },
            }

            try {
                await api.hogFunctions.createTestInvocation('new', {
                    configuration,
                    globals,
                    mock_async_functions: false,
                })
                breakpoint()
                lemonToast.success('Test invocation sent')
            } catch (e: any) {
                breakpoint()
                lemonToast.error(e.detail || 'Test invocation failed')
            }

            actions.testConfigurationComplete()
        },

        submitConfiguration: async () => {
            try {
                const destinationKey = values.selectedDestinationKey
                const triggerKey = values.selectedTriggerKey

                if (!destinationKey || !triggerKey) {
                    return
                }

                const destination = values.allDestinations.find((d) => d.key === destinationKey)!
                const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[triggerKey]
                const subTemplate = subTemplates.find((t) => t.template_id === destination.templateId)

                if (!subTemplate) {
                    lemonToast.error('Template not found for this combination')
                    return
                }

                const mergedInputs: Record<string, any> = { ...subTemplate.inputs }
                for (const [key, val] of Object.entries(values.inputValues)) {
                    mergedInputs[key] = val
                }

                const filters = applyKindFilter(subTemplate.filters, values.selectedKinds)
                const name = decorateAlertName(subTemplate.name ?? '', values.selectedKinds)
                const description = decorateAlertName(subTemplate.description ?? '', values.selectedKinds)

                const configuration: Record<string, any> = {
                    type: 'internal_destination',
                    template_id: destination.templateId,
                    name,
                    description,
                    filters,
                    enabled: true,
                    masking: null,
                    inputs: mergedInputs,
                }

                await api.hogFunctions.create(configuration)
                posthog.capture('error_tracking_alert_created', {
                    source: 'wizard',
                    trigger_event: subTemplate.filters?.events?.[0]?.id ?? null,
                    subtemplate_id: triggerKey,
                    destination_key: destination.key,
                    destination_template_id: destination.templateId,
                    enabled: true,
                })
                lemonToast.success('Alert created successfully')
                actions.createAlertSuccess()
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to create alert')
            } finally {
                actions.submitConfigurationComplete()
            }
        },
    })),

    actionToUrl(({ values, props: logicProps }) => {
        if (logicProps.disableUrlSync) {
            return {}
        }

        const buildURL = (): [string, Record<string, any>, Record<string, any>] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }

            if (values.alertCreationView === AlertCreationView.Wizard) {
                searchParams.wizard_step = values.currentStep
                if (values.selectedDestinationKey) {
                    searchParams.wizard_dest = values.selectedDestinationKey
                } else {
                    delete searchParams.wizard_dest
                }
                if (values.selectedTriggerKey) {
                    searchParams.wizard_trigger = values.selectedTriggerKey
                } else {
                    delete searchParams.wizard_trigger
                }
            } else {
                delete searchParams.wizard_step
                delete searchParams.wizard_dest
                delete searchParams.wizard_trigger
            }

            return [currentLocation.pathname, searchParams, currentLocation.hashParams]
        }

        return {
            setAlertCreationView: buildURL,
            setStep: buildURL,
            setDestinationKey: buildURL,
            setTriggerKey: buildURL,
            resetWizard: buildURL,
            createAlertSuccess: buildURL,
        }
    }),

    urlToAction(({ actions, values, props: logicProps }) => ({
        '**': (_, searchParams) => {
            if (logicProps.disableUrlSync) {
                return
            }
            const wizardStep = searchParams.wizard_step as WizardStep | undefined
            const wizardDest = searchParams.wizard_dest as string | undefined
            const wizardTrigger = searchParams.wizard_trigger as HogFunctionSubTemplateIdType | undefined

            if (wizardStep && values.alertCreationView !== AlertCreationView.Wizard) {
                actions.restoreWizardState({
                    step: wizardStep,
                    destinationKey: wizardDest ?? null,
                    triggerKey: wizardTrigger ?? null,
                })
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExistingAlerts()
    }),
])

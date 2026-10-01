import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, Breadcrumb } from '~/types'

import {
    llmAnalyticsScoreDefinitionsCreate,
    llmAnalyticsScoreDefinitionsNewVersionCreate,
    llmAnalyticsScoreDefinitionsPartialUpdate,
    llmAnalyticsScoreDefinitionsRetrieve,
} from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { getBooleanConfig } from './scoreDefinitionConfigUtils'
import {
    buildConfigFromDraft,
    createDraft,
    getApiErrorDetail,
    getCurrentProjectId,
    type ScoreDefinitionDraft,
    validateDraft,
} from './scoreDefinitionModalUtils'

export interface ScorerLogicProps {
    scorerId: string
    duplicateFrom?: string
}

export interface scorerLogicValues {
    definition: ScoreDefinitionApi | null
    definitionLoading: boolean
    draft: ScoreDefinitionDraft
    error: string | null
    loadError: string | null
    saving: boolean
    isNew: boolean
    hasChanges: boolean
    hasUnsavedChanges: boolean
    configChanged: boolean
    willCreateVersion: boolean
    breadcrumbs: Breadcrumb[]
}

export interface scorerLogicActions {
    loadDefinition: () => { value: true }
    loadDefinitionSuccess: (definition: ScoreDefinitionApi | null) => { definition: ScoreDefinitionApi | null }
    loadDefinitionFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    initialize: (definition: ScoreDefinitionApi | null) => { definition: ScoreDefinitionApi | null }
    setDraftField: (
        field: keyof ScoreDefinitionDraft,
        value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]
    ) => { field: keyof ScoreDefinitionDraft; value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft] }
    updateOptionLabel: (index: number, value: string) => { index: number; value: string }
    addOption: () => { value: true }
    removeOption: (index: number) => { index: number }
    save: () => { value: true }
    performSave: () => { value: true }
    createVersion: () => { value: true }
    performCreateVersion: () => { value: true }
    toggleArchive: () => { value: true }
    performToggleArchive: () => { value: true }
    setSaving: (saving: boolean) => { saving: boolean }
    setError: (error: string | null) => { error: string | null }
}

export type scorerLogicType = MakeLogicType<scorerLogicValues, scorerLogicActions, ScorerLogicProps>

export const scorerLogic = kea<scorerLogicType>([
    props({} as ScorerLogicProps),
    key(({ scorerId, duplicateFrom }) => `${getCurrentProjectId()}-${scorerId}-${duplicateFrom || ''}`),
    path((key) => ['products', 'ai_observability', 'frontend', 'scoreDefinitions', 'scorerLogic', key]),
    actions({
        loadDefinition: true,
        initialize: (definition: ScoreDefinitionApi | null) => ({ definition }),
        setDraftField: (
            field: keyof ScoreDefinitionDraft,
            value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]
        ) => ({
            field,
            value,
        }),
        updateOptionLabel: (index: number, value: string) => ({ index, value }),
        addOption: true,
        removeOption: (index: number) => ({ index }),
        save: true,
        performSave: true,
        createVersion: true,
        performCreateVersion: true,
        toggleArchive: true,
        performToggleArchive: true,
        setSaving: (saving: boolean) => ({ saving }),
        setError: (error: string | null) => ({ error }),
    }),
    loaders(({ props }) => ({
        definition: [
            null as ScoreDefinitionApi | null,
            {
                loadDefinition: async (_, breakpoint) => {
                    const teamId = getCurrentProjectId()
                    const definition = await llmAnalyticsScoreDefinitionsRetrieve(
                        teamId,
                        (props.scorerId === 'new' && props.duplicateFrom) || props.scorerId
                    )
                    breakpoint()
                    return teamId === getCurrentProjectId() ? definition : null
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        definition: [null as ScoreDefinitionApi | null, { initialize: (_, { definition }) => definition }],
        draft: [
            createDraft('create'),
            {
                initialize: (_, { definition }) =>
                    createDraft(
                        props.scorerId === 'new' && props.duplicateFrom
                            ? 'duplicate'
                            : definition
                              ? 'metadata'
                              : 'create',
                        definition
                    ),
                setDraftField: (state, { field, value }) => ({ ...state, [field]: value }),
                updateOptionLabel: (state, { index, value }) => ({
                    ...state,
                    options: state.options.map((option, optionIndex) =>
                        optionIndex === index ? { ...option, label: value } : option
                    ),
                }),
                addOption: (state) => ({ ...state, options: [...state.options, { key: '', label: '' }] }),
                removeOption: (state, { index }) => ({
                    ...state,
                    options: state.options.filter((_, optionIndex) => optionIndex !== index),
                }),
            },
        ],
        saving: [false, { setSaving: (_, { saving }) => saving }],
        error: [null as string | null, { setError: (_, { error }) => error, initialize: () => null }],
        loadError: [
            null as string | null,
            {
                loadDefinition: () => null,
                loadDefinitionSuccess: () => null,
                loadDefinitionFailure: () => 'Could not load this scorer. Try again.',
            },
        ],
    })),
    selectors({
        isNew: [() => [(_, props) => props.scorerId], (scorerId) => scorerId === 'new'],
        configChanged: [
            (s) => [s.draft, s.definition],
            (draft, definition) =>
                !!definition &&
                JSON.stringify(buildConfigFromDraft(draft)) !==
                    JSON.stringify(buildConfigFromDraft(createDraft('metadata', definition))),
        ],
        hasChanges: [
            (s) => [s.isNew, s.configChanged, s.draft, s.definition],
            (isNew, configChanged, draft, definition) =>
                isNew ||
                configChanged ||
                draft.name.trim() !== definition?.name ||
                draft.description.trim() !== definition?.description,
        ],
        willCreateVersion: [
            (s) => [s.isNew, s.hasChanges, s.configChanged, s.definition],
            (isNew, hasChanges, configChanged, definition) =>
                !isNew &&
                hasChanges &&
                (configChanged ||
                    (definition?.kind === 'boolean' && getBooleanConfig(definition.config).true_is_failure == null)),
        ],
        hasUnsavedChanges: [
            (s) => [s.draft, s.definition, (_, props) => props],
            (draft, definition, props: ScorerLogicProps) =>
                JSON.stringify(draft) !==
                JSON.stringify(
                    createDraft(
                        props.scorerId === 'new' && props.duplicateFrom
                            ? 'duplicate'
                            : definition
                              ? 'metadata'
                              : 'create',
                        definition
                    )
                ),
        ],
        breadcrumbs: [
            (s) => [s.isNew, s.definition],
            (isNew, definition): Breadcrumb[] => [
                { name: 'Scorers', path: urls.aiObservabilityScorers(), key: 'AIObservabilityScorers' },
                { name: isNew ? 'New scorer' : definition?.name || 'Scorer', key: 'AIObservabilityScorer' },
            ],
        ],
    }),
    listeners(({ actions, values, props }) => ({
        loadDefinitionSuccess: ({ definition }) => actions.initialize(definition),
        save: () => {
            if (
                values.saving ||
                values.definitionLoading ||
                !values.hasChanges ||
                (!values.isNew && !values.definition) ||
                getAccessControlDisabledReason(AccessControlResourceType.LlmAnalytics, AccessControlLevel.Editor)
            ) {
                return
            }
            const validationError = validateDraft('create', values.draft)
            if (validationError) {
                actions.setError(validationError)
                return
            }
            actions.setSaving(true)
            actions.performSave()
        },
        performSave: async (_, breakpoint) => {
            const teamId = getCurrentProjectId()
            const { draft, definition, isNew, willCreateVersion } = values
            const metadata = { name: draft.name.trim(), description: draft.description.trim() }
            const operation = isNew ? 'create' : willCreateVersion ? 'version' : 'metadata'
            actions.setError(null)
            posthog.capture('ai scorer save started', { operation, kind: draft.kind })
            try {
                const saved = isNew
                    ? await llmAnalyticsScoreDefinitionsCreate(teamId, {
                          ...metadata,
                          kind: draft.kind,
                          config: buildConfigFromDraft(draft),
                      })
                    : willCreateVersion
                      ? await llmAnalyticsScoreDefinitionsNewVersionCreate(teamId, props.scorerId, {
                            ...metadata,
                            config: buildConfigFromDraft(draft),
                            base_version: definition!.current_version,
                        })
                      : await llmAnalyticsScoreDefinitionsPartialUpdate(teamId, props.scorerId, metadata)
                breakpoint()
                if (teamId !== getCurrentProjectId()) {
                    return
                }
                if (!isNew) {
                    actions.initialize(saved)
                }
                posthog.capture('ai scorer saved', { operation, kind: saved.kind })
                lemonToast.success(isNew ? 'Scorer created.' : 'Scorer saved.')
                if (isNew) {
                    router.actions.replace(urls.aiObservabilityScorer(saved.id))
                }
            } catch (error) {
                breakpoint()
                const stale = typeof error === 'object' && error !== null && 'status' in error && error.status === 409
                actions.setError(
                    stale
                        ? 'This scorer has a newer version. Reload the scorer and review your changes before saving.'
                        : getApiErrorDetail(error) || 'Could not save this scorer. Try again.'
                )
                posthog.capture('ai scorer save failed', { operation, kind: draft.kind })
            } finally {
                actions.setSaving(false)
            }
        },
        createVersion: () => {
            if (
                values.saving ||
                values.definitionLoading ||
                !values.definition ||
                values.hasChanges ||
                getAccessControlDisabledReason(AccessControlResourceType.LlmAnalytics, AccessControlLevel.Editor)
            ) {
                return
            }
            actions.setSaving(true)
            actions.performCreateVersion()
        },
        performCreateVersion: async (_, breakpoint) => {
            const definition = values.definition!
            const teamId = getCurrentProjectId()
            actions.setError(null)
            try {
                const saved = await llmAnalyticsScoreDefinitionsNewVersionCreate(teamId, definition.id, {
                    config:
                        definition.kind === 'boolean'
                            ? buildConfigFromDraft(createDraft('config', definition))
                            : definition.config,
                    base_version: definition.current_version,
                })
                breakpoint()
                if (teamId === getCurrentProjectId()) {
                    actions.initialize(saved)
                    posthog.capture('ai scorer version created', { kind: saved.kind })
                    lemonToast.success(`Created version ${saved.current_version}.`)
                }
            } catch (error) {
                breakpoint()
                actions.setError(
                    getApiErrorDetail(error) || 'Could not create a version. Reload this scorer and try again.'
                )
            } finally {
                actions.setSaving(false)
            }
        },
        toggleArchive: () => {
            if (
                values.saving ||
                values.definitionLoading ||
                !values.definition ||
                values.hasChanges ||
                getAccessControlDisabledReason(AccessControlResourceType.LlmAnalytics, AccessControlLevel.Editor)
            ) {
                return
            }
            actions.setSaving(true)
            actions.performToggleArchive()
        },
        performToggleArchive: async (_, breakpoint) => {
            const definition = values.definition!
            const teamId = getCurrentProjectId()
            actions.setError(null)
            try {
                const saved = await llmAnalyticsScoreDefinitionsPartialUpdate(teamId, definition.id, {
                    archived: !definition.archived,
                })
                breakpoint()
                if (teamId === getCurrentProjectId()) {
                    actions.initialize(saved)
                    posthog.capture('ai scorer archive changed', { archived: saved.archived })
                }
            } catch (error) {
                breakpoint()
                actions.setError(getApiErrorDetail(error) || 'Could not update this scorer. Try again.')
            } finally {
                actions.setSaving(false)
            }
        },
    })),
    beforeUnload(({ values }) => ({
        enabled: () => values.hasUnsavedChanges && !values.saving,
        message: 'Leave this scorer? Your unsaved changes will be discarded.',
    })),
    afterMount(({ actions, props }) => {
        posthog.capture('ai scorer editor opened', {
            creating: props.scorerId === 'new',
            duplicating: !!props.duplicateFrom,
        })
        if (props.scorerId !== 'new' || props.duplicateFrom) {
            actions.loadDefinition()
        }
    }),
])

import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { beforeUnload, router } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { subscriptions } from 'kea-subscriptions'

import { readableErrorMessage } from 'lib/api-error'
import { isEmptyProperty, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils/objects'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    FeatureFlagConfig,
    FeatureFlagRulesV2DraftConfig,
    FeatureFlagRulesV2DraftRule,
    FeatureFlagRulesV2ReturnType,
    FeatureFlagType,
    PropertyOperator,
    TeamPublicType,
    TeamType,
} from '~/types'

import {
    isRulesV2FeatureFlagConfig,
    isStaleRowVersionError,
    rulesV2CreateDisabledReason,
} from 'products/feature_flags/frontend/featureFlagConfigFormat'
import { featureFlagsCreate, featureFlagsPartialUpdate } from 'products/feature_flags/frontend/generated/api'
import type {
    FeatureFlagCreateRequestSchemaApi,
    PatchedFeatureFlagPartialUpdateRequestSchemaApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

import { checkFeatureFlagConfirmation } from './featureFlagConfirmationLogic'
import { confirmFeatureFlagKeyChange } from './featureFlagKeyChangeDialog'
import {
    FeatureFlagLogicProps,
    featureFlagLogic,
    validateFeatureFlagKey,
    variantKeyToIndexFeatureFlagPayloads,
} from './featureFlagLogic'
import {
    moved,
    newVariantSplitFields,
    rulesV2DraftErrors,
    rulesV2InitialValue,
    withReturnType,
} from './featureFlagRulesV2Draft'

export interface FeatureFlagRulesV2Draft {
    key: string
    name: string
    tags: string[]
    config: FeatureFlagRulesV2DraftConfig
    /** The row version the draft was loaded from, so a save never pairs old rules with a newer version. */
    version: number | null
}

/** The first save error, keyed to the editor field its path names; `field` is null when no field owns it. */
export interface RulesV2SaveError {
    field: string | null
    message: string
}

export interface RulesV2WriteBody {
    key: string
    name: string
    tags: string[]
    filters: FeatureFlagRulesV2DraftConfig
    version?: number
}

export const NEW_RULES_V2_DRAFT: FeatureFlagRulesV2Draft = {
    key: '',
    name: '',
    tags: [],
    config: { version: 2, return_type: 'boolean', default_value: false, rules: [] },
    version: null,
}

export const BOOLEAN_OPTIONS = [
    { value: 'true', label: 'true' },
    { value: 'false', label: 'false' },
]

export const NEW_TARGETED_RELEASE_RULE: FeatureFlagRulesV2DraftRule = {
    rule_type: 'targeted_release',
    targeting: { properties: [] },
    value: true,
}

// The rollout fields a rule gains when it becomes a percentage rollout; the server assigns its seed.
export const NEW_ROLLOUT_FIELDS = {
    rollout_percentage: 0,
    on_rollout_miss: 'continue',
    assignment_algorithm: 'sha1_60_v1',
    assign_by: 'person',
} as const

const NEW_SPLIT_ROLLOUT_FIELDS = { ...NEW_ROLLOUT_FIELDS, rollout_percentage: 100 } as const

// React keys for rule cards: new rules have no id, and index keys would follow a moved rule's position.
let lastRuleKey = 0
const nextRuleKey = (): number => ++lastRuleKey

/**
 * Keeps the rule's identity and shared fields; type-specific fields come and go with the type. A rollout keeps its
 * percentage and miss behaviour between the two randomized types. The seed is dropped, and the server keeps the
 * stored one for as long as the rule stays randomized.
 */
export function withRuleType(
    rule: FeatureFlagRulesV2DraftRule,
    ruleType: FeatureFlagRulesV2DraftRule['rule_type'],
    returnType: FeatureFlagRulesV2ReturnType
): FeatureFlagRulesV2DraftRule {
    if (rule.rule_type === ruleType) {
        return rule
    }
    const { id, targeting, description, metadata } = rule
    const shared = { id, targeting, description, metadata }
    const value = rule.rule_type === 'experiment' ? rulesV2InitialValue(returnType) : rule.value
    const rollout =
        rule.rule_type === 'targeted_release'
            ? null
            : {
                  rollout_percentage: rule.rollout_percentage,
                  on_rollout_miss: rule.on_rollout_miss,
                  assignment_algorithm: rule.assignment_algorithm,
                  assign_by: rule.assign_by,
              }
    switch (ruleType) {
        case 'targeted_release':
            return { ...shared, rule_type: ruleType, value }
        case 'percentage_rollout':
            return { ...shared, rule_type: ruleType, value, ...(rollout ?? NEW_ROLLOUT_FIELDS) }
        case 'experiment':
            return {
                ...shared,
                rule_type: ruleType,
                ...(rollout ?? NEW_SPLIT_ROLLOUT_FIELDS),
                ...newVariantSplitFields(returnType),
            }
    }
}

/** The draft holds the stored document as loaded, seeds and unrendered fields included, so a save echoes them. */
export function rulesV2DraftFromFlag(flag: FeatureFlagType): FeatureFlagRulesV2Draft {
    if (!isRulesV2FeatureFlagConfig(flag.filters)) {
        return NEW_RULES_V2_DRAFT
    }
    return {
        key: flag.key,
        name: flag.name ?? '',
        tags: flag.tags ?? [],
        config: flag.filters,
        version: flag.version,
    }
}

/** A create carries no row version; an update replaces the whole document and must carry it. */
export function rulesV2WriteBody(draft: FeatureFlagRulesV2Draft): RulesV2WriteBody {
    return {
        key: draft.key,
        name: draft.name,
        tags: draft.tags,
        filters: draft.config,
        ...(draft.version != null ? { version: draft.version } : {}),
    }
}

const RULE_FIELDS = [
    'rule_type',
    'description',
    'targeting',
    'value',
    'rollout_percentage',
    'on_rollout_miss',
    'paused',
    'seed',
    'variants',
    'variants[]',
    'variants[].key',
    'variants[].weight',
    'variants[].value',
    'holdout',
    'holdout.exclusion_percentage',
    'holdout.seed',
]
// The paths, with list indices removed, that the editor shows an error against.
const EDITOR_FIELDS = new Set([
    'key',
    'name',
    'tags',
    'filters.return_type',
    'filters.default_value',
    'filters.rules[]',
    ...RULE_FIELDS.map((field) => `filters.rules[].${field}`),
])

/** The longest prefix of `path` that the editor has a field for, so a nested error lands on its nearest field. */
function editorField(path: string): string | null {
    let prefix: string | undefined = path
    while (prefix) {
        if (EDITOR_FIELDS.has(prefix.replace(/\[\d+\]/g, '[]'))) {
            return prefix
        }
        prefix = /^(.+)(?:\.\w+|\[\d+\])$/.exec(prefix)?.[1]
    }
    return null
}

/** Field errors arrive with `attr`; document errors arrive as `detail` prefixed with their `filters…` path. */
export function rulesV2SaveError(error: any): RulesV2SaveError {
    const detail = readableErrorMessage(error) ?? 'This flag could not be saved.'
    const prefixed = error?.attr ? null : /^(filters(?:\.\w+|\[\d+\])*): (.+)$/s.exec(detail)
    const path: string | null = error?.attr || prefixed?.[1] || null
    const field = path ? editorField(path) : null
    // Only an exact field match drops the path; everything else is shown verbatim.
    const exact = field !== null && field === path
    return { field, message: exact && prefixed ? prefixed[2] : detail }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagRulesV2EditorLogicValues {
    enabledFeatures: FeatureFlagsSet // featureFlagLogic
    featureFlag: FeatureFlagType // featureFlagLogic
    currentProjectId: number | null // projectLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    draft: FeatureFlagRulesV2Draft
    draftErrors: Record<string, string>
    fieldError: (field: string) => string | null
    hasUnsavedChanges: boolean
    ruleKeys: number[]
    saveDisabledReason: string | null
    saveError: RulesV2SaveError | null
    saving: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagRulesV2EditorLogicActions {
    editFeatureFlag: (
        editing: boolean,
        options?:
            | {
                  expandAdvanced?: boolean
              }
            | undefined
    ) => {
        editing: boolean
        expandAdvanced: boolean
    } // featureFlagLogic
    loadFeatureFlagSuccess: (
        featureFlag: FeatureFlagType,
        payload?: any
    ) => {
        featureFlag: FeatureFlagType
        payload?: any
    } // featureFlagLogic
    refreshFeatureFlag: (
        payload?:
            | {
                  afterAgentChange?: boolean
              }
            | undefined
    ) => {
        afterAgentChange?: boolean
    } // featureFlagLogic
    setRulesV2DraftDirty: (dirty: boolean) => {
        dirty: boolean
    } // featureFlagLogic
    addRule: () => {
        value: true
    }
    loadDraft: (draft: FeatureFlagRulesV2Draft) => {
        draft: FeatureFlagRulesV2Draft
    }
    moveRule: (
        from: number,
        to: number
    ) => {
        from: number
        to: number
    }
    removeRule: (index: number) => {
        index: number
    }
    saveRulesV2Flag: () => {
        value: true
    }
    saveRulesV2FlagFailure: (error: RulesV2SaveError | null) => {
        error: RulesV2SaveError | null
    }
    saveRulesV2FlagSuccess: (flag: FeatureFlagType) => {
        flag: FeatureFlagType
    }
    setConfig: (config: Partial<FeatureFlagRulesV2DraftConfig>) => {
        config: Partial<FeatureFlagRulesV2DraftConfig>
    }
    setDraft: (draft: Partial<FeatureFlagRulesV2Draft>) => {
        draft: Partial<FeatureFlagRulesV2Draft>
    }
    setReturnType: (returnType: FeatureFlagRulesV2ReturnType) => {
        returnType: FeatureFlagRulesV2ReturnType
    }
    setRule: (
        index: number,
        rule: FeatureFlagRulesV2DraftRule
    ) => {
        index: number
        rule: FeatureFlagRulesV2DraftRule
    }
    submitRulesV2Flag: () => {
        value: true
    }
    updateRule: (
        index: number,
        rule: FeatureFlagRulesV2DraftRule
    ) => {
        index: number
        rule: FeatureFlagRulesV2DraftRule
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagRulesV2EditorLogicMeta {
    key: number | 'link' | 'new'
    __keaTypeGenInternalSelectorTypes: {
        draftErrors: (draft: FeatureFlagRulesV2Draft) => Record<string, string>
        fieldError: (
            saveError: RulesV2SaveError | null,
            draftErrors: Record<string, string>
        ) => (field: string) => string | null
        saveDisabledReason: (
            draft: FeatureFlagRulesV2Draft,
            draftErrors: Record<string, string>,
            currentTeam: TeamPublicType | TeamType | null,
            enabledFeatures: FeatureFlagsSet,
            id: number | 'link' | 'new'
        ) => string | null
    }
}

export type featureFlagRulesV2EditorLogicType = MakeLogicType<
    featureFlagRulesV2EditorLogicValues,
    featureFlagRulesV2EditorLogicActions,
    FeatureFlagLogicProps,
    featureFlagRulesV2EditorLogicMeta
>

export const featureFlagRulesV2EditorLogic = kea<featureFlagRulesV2EditorLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagRulesV2EditorLogic']),
    props({} as FeatureFlagLogicProps),
    key(({ id }) => id),
    connect((props: FeatureFlagLogicProps) => ({
        values: [
            featureFlagLogic(props),
            ['featureFlag', 'enabledFeatures'],
            projectLogic,
            ['currentProjectId'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [
            featureFlagLogic(props),
            ['editFeatureFlag', 'loadFeatureFlagSuccess', 'refreshFeatureFlag', 'setRulesV2DraftDirty'],
        ],
    })),
    actions({
        loadDraft: (draft: FeatureFlagRulesV2Draft) => ({ draft }),
        setDraft: (draft: Partial<FeatureFlagRulesV2Draft>) => ({ draft }),
        setConfig: (config: Partial<FeatureFlagRulesV2DraftConfig>) => ({ config }),
        setReturnType: (returnType: FeatureFlagRulesV2ReturnType) => ({ returnType }),
        addRule: true,
        updateRule: (index: number, rule: FeatureFlagRulesV2DraftRule) => ({ index, rule }),
        setRule: (index: number, rule: FeatureFlagRulesV2DraftRule) => ({ index, rule }),
        removeRule: (index: number) => ({ index }),
        moveRule: (from: number, to: number) => ({ from, to }),
        saveRulesV2Flag: true,
        submitRulesV2Flag: true,
        saveRulesV2FlagSuccess: (flag: FeatureFlagType) => ({ flag }),
        saveRulesV2FlagFailure: (error: RulesV2SaveError | null) => ({ error }),
    }),
    reducers({
        draft: [
            NEW_RULES_V2_DRAFT,
            {
                loadDraft: (_, { draft }) => draft,
                setDraft: (state, { draft }) => ({ ...state, ...draft }),
                setConfig: (state, { config }) => ({ ...state, config: { ...state.config, ...config } }),
                setReturnType: (state, { returnType }) => ({
                    ...state,
                    config: withReturnType(state.config, returnType),
                }),
                addRule: (state) => ({
                    ...state,
                    config: {
                        ...state.config,
                        rules: [
                            ...state.config.rules,
                            { ...NEW_TARGETED_RELEASE_RULE, value: rulesV2InitialValue(state.config.return_type) },
                        ],
                    },
                }),
                setRule: (state, { index, rule }) => ({
                    ...state,
                    config: { ...state.config, rules: state.config.rules.map((r, i) => (i === index ? rule : r)) },
                }),
                removeRule: (state, { index }) => ({
                    ...state,
                    config: { ...state.config, rules: state.config.rules.filter((_, i) => i !== index) },
                }),
                moveRule: (state, { from, to }) => ({
                    ...state,
                    config: { ...state.config, rules: moved(state.config.rules, from, to) },
                }),
            },
        ],
        ruleKeys: [
            [] as number[],
            {
                loadDraft: (_, { draft }) => draft.config.rules.map(nextRuleKey),
                setDraft: (state, { draft }) => (draft.config ? draft.config.rules.map(nextRuleKey) : state),
                setConfig: (state, { config }) => (config.rules ? config.rules.map(nextRuleKey) : state),
                addRule: (state) => [...state, nextRuleKey()],
                removeRule: (state, { index }) => state.filter((_, i) => i !== index),
                moveRule: (state, { from, to }) => moved(state, from, to),
            },
        ],
        // Rule indices shift on any edit, so an error is only shown against the document it came from.
        saveError: [
            null as RulesV2SaveError | null,
            {
                saveRulesV2FlagFailure: (_, { error }) => error,
                saveRulesV2Flag: () => null,
                setDraft: () => null,
                setConfig: () => null,
                setReturnType: () => null,
                addRule: () => null,
                setRule: () => null,
                removeRule: () => null,
                moveRule: () => null,
            },
        ],
        hasUnsavedChanges: [
            false,
            {
                loadDraft: () => false,
                saveRulesV2FlagSuccess: () => false,
                setDraft: () => true,
                setConfig: () => true,
                setReturnType: () => true,
                addRule: () => true,
                setRule: () => true,
                removeRule: () => true,
                moveRule: () => true,
            },
        ],
        saving: [
            false,
            {
                submitRulesV2Flag: () => true,
                saveRulesV2FlagSuccess: () => false,
                saveRulesV2FlagFailure: () => false,
            },
        ],
    }),
    selectors({
        draftErrors: [
            (s) => [s.draft],
            (draft: FeatureFlagRulesV2Draft): Record<string, string> => rulesV2DraftErrors(draft.config),
        ],
        // The server's error wins: it is about the document as it was sent.
        fieldError: [
            (s) => [s.saveError, s.draftErrors],
            (saveError: RulesV2SaveError | null, draftErrors: Record<string, string>) =>
                (field: string): string | null =>
                    saveError?.field === field ? saveError.message : (draftErrors[field] ?? null),
        ],
        saveDisabledReason: [
            (s, p) => [s.draft, s.draftErrors, s.currentTeam, s.enabledFeatures, p.id],
            (
                draft: FeatureFlagRulesV2Draft,
                draftErrors: Record<string, string>,
                currentTeam: TeamPublicType | TeamType | null,
                enabledFeatures: FeatureFlagsSet,
                id: FeatureFlagLogicProps['id']
            ): string | null => {
                // The list disables this entry point, but a direct link still opens the editor.
                const createDisabledReason =
                    id === 'new' ? rulesV2CreateDisabledReason(currentTeam, enabledFeatures) : null
                if (createDisabledReason) {
                    return createDisabledReason
                }
                const keyError = validateFeatureFlagKey(draft.key)
                if (keyError) {
                    return keyError
                }
                const [firstErrorField, firstError] = Object.entries(draftErrors)[0] ?? []
                if (firstErrorField) {
                    const ruleIndex = Number(/^filters\.rules\[(\d+)\]/.exec(firstErrorField)?.[1])
                    return `Rule ${ruleIndex + 1}: ${firstError}`
                }
                // The server accepts a condition with no value, but the condition never matches.
                // Set and not-set conditions take no value, so they are not incomplete.
                const emptyConditionIndex = draft.config.rules.findIndex((rule) =>
                    rule.targeting.properties.some(
                        (property) =>
                            isEmptyProperty(property) &&
                            !(
                                isPropertyFilterWithOperator(property) &&
                                [PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(property.operator)
                            )
                    )
                )
                return emptyConditionIndex >= 0
                    ? `Choose a value for every condition in rule ${emptyConditionIndex + 1}.`
                    : null
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        // Inputs such as PercentageInput report a change on every blur, and an unchanged rule is not an edit.
        updateRule: ({ index, rule }) => {
            if (!objectsEqual(values.draft.config.rules[index], rule)) {
                actions.setRule(index, rule)
            }
        },
        saveRulesV2Flag: async () => {
            const storedFlag = values.featureFlag
            if (
                storedFlag.id &&
                storedFlag.key !== values.draft.key &&
                !(await confirmFeatureFlagKeyChange(storedFlag.key))
            ) {
                return
            }
            // The server does not enforce the project's confirmation setting, so this check is the only gate.
            // The draft holds the stored seeds, so only a real edit differs from the stored document.
            const confirmationEnabled = !!values.currentTeam?.feature_flag_confirmation_enabled
            const confirmationShown = checkFeatureFlagConfirmation(
                storedFlag,
                { ...storedFlag, key: values.draft.key, filters: values.draft.config as FeatureFlagConfig },
                confirmationEnabled,
                confirmationEnabled ? values.currentTeam?.feature_flag_confirmation_message : undefined,
                confirmationEnabled,
                actions.submitRulesV2Flag
            )
            if (!confirmationShown) {
                actions.submitRulesV2Flag()
            }
        },
        submitRulesV2Flag: async () => {
            const projectId = String(values.currentProjectId)
            const body = rulesV2WriteBody(values.draft)
            try {
                // The wire types describe the v1 document; the v2 document travels under the same `filters` key.
                const saved =
                    props.id === 'new'
                        ? await featureFlagsCreate(projectId, body as unknown as FeatureFlagCreateRequestSchemaApi)
                        : await featureFlagsPartialUpdate(
                              projectId,
                              props.id as number,
                              body as unknown as PatchedFeatureFlagPartialUpdateRequestSchemaApi
                          )
                actions.saveRulesV2FlagSuccess(saved as unknown as FeatureFlagType)
            } catch (error: any) {
                if (isStaleRowVersionError(body, error)) {
                    lemonToast.error(
                        'This flag changed while you were editing it. It has been reloaded; your edits were not saved.'
                    )
                    actions.saveRulesV2FlagFailure(null)
                    actions.editFeatureFlag(false)
                    actions.refreshFeatureFlag()
                    return
                }
                const saveError = rulesV2SaveError(error)
                actions.saveRulesV2FlagFailure(saveError)
                // The inline error can sit off-screen and is not announced, so a toast reports the rejection too.
                lemonToast.error(`Flag not saved: ${saveError.message}`)
            }
        },
        saveRulesV2FlagSuccess: ({ flag }) => {
            lemonToast.success('Flag saved')
            if (flag.id) {
                refreshTreeItem('feature_flag', String(flag.id))
            }
            if (props.id === 'new') {
                router.actions.push(urls.featureFlag(flag.id ?? 'new'))
                return
            }
            // The response is the stored flag, so the page takes it without a second request.
            actions.loadFeatureFlagSuccess(variantKeyToIndexFeatureFlagPayloads(flag))
            actions.editFeatureFlag(false)
        },
    })),
    // featureFlagLogic resets the page on a same-URL navigation unless it knows the draft is dirty.
    subscriptions(({ actions }) => ({
        hasUnsavedChanges: (dirty: boolean) => actions.setRulesV2DraftDirty(dirty),
    })),
    beforeUnmount(({ actions }) => actions.setRulesV2DraftDirty(false)),
    beforeUnload(({ values }) => ({
        // In-page URL updates such as opening the side panel keep the pathname and the draft.
        enabled: (newLocation?: CombinedLocation) =>
            values.hasUnsavedChanges && newLocation?.pathname !== router.values.location.pathname,
        message: 'Leave this flag?\nChanges you made will be discarded.',
    })),
    afterMount(({ actions, values, props }) => {
        if (typeof props.id === 'number') {
            actions.loadDraft(rulesV2DraftFromFlag(values.featureFlag))
        }
    }),
])

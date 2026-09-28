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

import { isApprovalRequiredError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import {
    FeatureFlagRulesV2DraftConfig,
    FeatureFlagRulesV2DraftRule,
    FeatureFlagRulesV2Rule,
    FeatureFlagType,
} from '~/types'

import { featureFlagsCreate, featureFlagsPartialUpdate } from 'products/feature_flags/frontend/generated/api'
import type {
    FeatureFlagCreateRequestSchemaApi,
    PatchedFeatureFlagPartialUpdateRequestSchemaApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

import { isRulesV2FeatureFlagConfig } from './featureFlagConfigFormat'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'

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

// React keys for rule cards: new rules have no id, and index keys would follow a moved rule's position.
let lastRuleKey = 0
const nextRuleKey = (): number => ++lastRuleKey

function moved<T>(items: T[], from: number, to: number): T[] {
    const result = [...items]
    result.splice(to, 0, ...result.splice(from, 1))
    return result
}

const RULE_FIELDS = new Set(['rule_type', 'description', 'targeting', 'value', 'rollout_percentage', 'on_rollout_miss'])

/** Keeps the rule's identity and shared fields; rollout fields come and go with the type. */
export function withRuleType(
    rule: FeatureFlagRulesV2DraftRule,
    ruleType: FeatureFlagRulesV2DraftRule['rule_type']
): FeatureFlagRulesV2DraftRule {
    if (rule.rule_type === ruleType) {
        return rule
    }
    const { id, targeting, description, metadata, value } = rule
    const shared = { id, targeting, description, metadata, value }
    return ruleType === 'percentage_rollout'
        ? { ...shared, rule_type: ruleType, ...NEW_ROLLOUT_FIELDS }
        : { ...shared, rule_type: ruleType }
}

function toDraftRule(rule: FeatureFlagRulesV2Rule): FeatureFlagRulesV2DraftRule {
    if (rule.rule_type === 'targeted_release') {
        return rule
    }
    if (rule.rule_type === 'percentage_rollout') {
        const { seed: _seed, ...draftRule } = rule
        return draftRule
    }
    // Only editable documents reach the editor; dropping a rule here would delete it on save.
    throw new Error('Experiment rules cannot be edited here.')
}

export function rulesV2DraftFromFlag(flag: FeatureFlagType): FeatureFlagRulesV2Draft {
    if (!isRulesV2FeatureFlagConfig(flag.filters)) {
        return NEW_RULES_V2_DRAFT
    }
    return {
        key: flag.key,
        name: flag.name ?? '',
        tags: flag.tags ?? [],
        config: { ...flag.filters, rules: flag.filters.rules.map(toDraftRule) },
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

function editorField(path: string): string | null {
    if (path === 'key' || path === 'name' || path === 'tags' || path === 'filters.default_value') {
        return path
    }
    const rule = /^filters\.rules\[(\d+)\](?:\.(\w+))?/.exec(path)
    if (!rule) {
        return null
    }
    return rule[2] && RULE_FIELDS.has(rule[2]) ? `filters.rules[${rule[1]}].${rule[2]}` : `filters.rules[${rule[1]}]`
}

/** Field errors arrive with `attr`; document errors arrive as `detail` prefixed with their `filters…` path. */
export function rulesV2SaveError(error: any): RulesV2SaveError {
    const detail: string = error?.detail || error?.message || 'This flag could not be saved.'
    const prefixed = error?.attr ? null : /^(filters(?:\.\w+|\[\d+\])*): (.+)$/s.exec(detail)
    const path: string | null = error?.attr || prefixed?.[1] || null
    const field = path ? editorField(path) : null
    // Only an exact field match drops the path; everything else is shown verbatim.
    const exact = field !== null && field === path
    return { field, message: exact && prefixed ? prefixed[2] : detail }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagRulesV2EditorLogicValues {
    currentProjectId: number | null // projectLogic
    draft: FeatureFlagRulesV2Draft
    featureFlag: FeatureFlagType // featureFlagLogic
    fieldError: (field: string) => string | null
    hasUnsavedChanges: boolean
    ruleKeys: number[]
    saveDisabledReason: string | null
    saveError: RulesV2SaveError | null
    saving: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagRulesV2EditorLogicActions {
    addRule: () => {
        value: true
    }
    editFeatureFlag: (
        editing: boolean,
        options?: {
            expandAdvanced?: boolean
        }
    ) => {
        editing: boolean
        expandAdvanced: boolean
    } // featureFlagLogic
    loadDraft: (draft: FeatureFlagRulesV2Draft) => {
        draft: FeatureFlagRulesV2Draft
    }
    loadFeatureFlag: () => void // featureFlagLogic
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
    setRulesV2DraftDirty: (dirty: boolean) => {
        dirty: boolean
    } // featureFlagLogic
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
    key: string | number
    __keaTypeGenInternalSelectorTypes: {
        saveDisabledReason: (draft: FeatureFlagRulesV2Draft) => string | null
        fieldError: (saveError: RulesV2SaveError | null) => (field: string) => string | null
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
        values: [featureFlagLogic(props), ['featureFlag'], projectLogic, ['currentProjectId']],
        actions: [featureFlagLogic(props), ['editFeatureFlag', 'loadFeatureFlag', 'setRulesV2DraftDirty']],
    })),
    actions({
        loadDraft: (draft: FeatureFlagRulesV2Draft) => ({ draft }),
        setDraft: (draft: Partial<FeatureFlagRulesV2Draft>) => ({ draft }),
        setConfig: (config: Partial<FeatureFlagRulesV2DraftConfig>) => ({ config }),
        addRule: true,
        updateRule: (index: number, rule: FeatureFlagRulesV2DraftRule) => ({ index, rule }),
        removeRule: (index: number) => ({ index }),
        moveRule: (from: number, to: number) => ({ from, to }),
        saveRulesV2Flag: true,
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
                addRule: (state) => ({
                    ...state,
                    config: { ...state.config, rules: [...state.config.rules, NEW_TARGETED_RELEASE_RULE] },
                }),
                updateRule: (state, { index, rule }) => ({
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
                addRule: () => null,
                updateRule: () => null,
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
                addRule: () => true,
                updateRule: () => true,
                removeRule: () => true,
                moveRule: () => true,
            },
        ],
        saving: [
            false,
            {
                saveRulesV2Flag: () => true,
                saveRulesV2FlagSuccess: () => false,
                saveRulesV2FlagFailure: () => false,
            },
        ],
    }),
    selectors({
        fieldError: [
            (s) => [s.saveError],
            (saveError: RulesV2SaveError | null) =>
                (field: string): string | null =>
                    saveError?.field === field ? saveError.message : null,
        ],
        saveDisabledReason: [
            (s) => [s.draft],
            (draft: FeatureFlagRulesV2Draft): string | null => {
                if (!draft.key.trim()) {
                    return 'Enter a flag key.'
                }
                const badRollout = draft.config.rules.some(
                    (rule) =>
                        rule.rule_type === 'percentage_rollout' &&
                        !(rule.rollout_percentage >= 0 && rule.rollout_percentage <= 100)
                )
                return badRollout ? 'Rollout percentages must be between 0 and 100.' : null
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        saveRulesV2Flag: async () => {
            const projectId = String(values.currentProjectId)
            try {
                // The wire types describe the v1 document; the v2 document travels under the same `filters` key.
                const saved =
                    props.id === 'new'
                        ? await featureFlagsCreate(
                              projectId,
                              rulesV2WriteBody(values.draft) as unknown as FeatureFlagCreateRequestSchemaApi
                          )
                        : await featureFlagsPartialUpdate(
                              projectId,
                              props.id as number,
                              rulesV2WriteBody(
                                  values.draft
                              ) as unknown as PatchedFeatureFlagPartialUpdateRequestSchemaApi
                          )
                actions.saveRulesV2FlagSuccess(saved as unknown as FeatureFlagType)
            } catch (error: any) {
                if (error?.status === 409 && !isApprovalRequiredError(error)) {
                    lemonToast.error(
                        'This flag changed while you were editing it. It has been reloaded; your edits were not saved.'
                    )
                    actions.saveRulesV2FlagFailure(null)
                    // A full load: the silent refresh keeps the loaded document and would show stale rules.
                    actions.editFeatureFlag(false)
                    actions.loadFeatureFlag()
                    return
                }
                actions.saveRulesV2FlagFailure(rulesV2SaveError(error))
            }
        },
        saveRulesV2FlagSuccess: ({ flag }) => {
            lemonToast.success('Flag saved')
            if (props.id === 'new') {
                router.actions.push(urls.featureFlag(flag.id ?? 'new'))
                return
            }
            actions.editFeatureFlag(false)
            actions.loadFeatureFlag()
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

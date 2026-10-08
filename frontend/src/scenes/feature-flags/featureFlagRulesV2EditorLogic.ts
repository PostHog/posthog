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
    FeatureFlagRulesV2Rule,
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
        fieldError: (saveError: RulesV2SaveError | null) => (field: string) => string | null
        saveDisabledReason: (
            draft: FeatureFlagRulesV2Draft,
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
                addRule: (state) => ({
                    ...state,
                    config: { ...state.config, rules: [...state.config.rules, NEW_TARGETED_RELEASE_RULE] },
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
        fieldError: [
            (s) => [s.saveError],
            (saveError: RulesV2SaveError | null) =>
                (field: string): string | null =>
                    saveError?.field === field ? saveError.message : null,
        ],
        saveDisabledReason: [
            (s, p) => [s.draft, s.currentTeam, s.enabledFeatures, p.id],
            (
                draft: FeatureFlagRulesV2Draft,
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
                const badRollout = draft.config.rules.some(
                    (rule) =>
                        rule.rule_type === 'percentage_rollout' &&
                        !(rule.rollout_percentage >= 0 && rule.rollout_percentage <= 100)
                )
                if (badRollout) {
                    return 'Rollout percentages must be between 0 and 100.'
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
            // Both sides are compared without seeds, because the draft never holds one and a stored seed would count as a change.
            const confirmationEnabled = !!values.currentTeam?.feature_flag_confirmation_enabled
            const confirmationShown = checkFeatureFlagConfirmation(
                { ...storedFlag, filters: rulesV2DraftFromFlag(storedFlag).config as FeatureFlagConfig },
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

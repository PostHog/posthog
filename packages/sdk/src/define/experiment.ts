import type { ExperimentsExperimentCreateInput, SurveysSurveyCreateInput } from '../generated/api.js'
import { type Definition, defineKind, isDefinition, type RefTo, withDependencies } from './definition.js'
import type { FlagDefinition } from './flag.js'

export interface ExperimentInput extends Omit<ExperimentsExperimentCreateInput, 'feature_flag_key'> {
    // The flag definition, or its key.
    feature_flag_key: FlagDefinition | string
}

export type ExperimentDefinition<Key extends string = string> = Definition<
    'experiment',
    Key,
    ExperimentsExperimentCreateInput
>

// Opt-in: an experiment is mostly runtime, so a stack holds one only when it exports it.
export function experiment<const Key extends string>(key: Key, input: ExperimentInput): ExperimentDefinition<Key> {
    const { feature_flag_key: flagKey, ...fields } = input
    // The experiment names its flag by key, so a flag definition given here is created first.
    const body = { ...fields, feature_flag_key: isDefinition(flagKey) ? flagKey.key : flagKey }
    return defineKind('experiment', key, withDependencies(body, isDefinition(flagKey) ? [flagKey] : []))
}

export interface SurveyInput extends Omit<SurveysSurveyCreateInput, 'linked_flag_id'> {
    linked_flag_id?: RefTo<'flag'> | null
}

export type SurveyDefinition<Key extends string = string> = Definition<'survey', Key, SurveyInput>

export function survey<const Key extends string>(key: Key, body: SurveyInput): SurveyDefinition<Key> {
    return defineKind('survey', key, body)
}

import type { CohortsCohortsCreateInput } from '../generated/api.js'
import { type Definition, defineKind } from './definition.js'

export type CohortInput = CohortsCohortsCreateInput

export type CohortDefinition<Key extends string = string> = Definition<'cohort', Key, CohortInput>

export function cohort<const Key extends string>(key: Key, body: CohortInput): CohortDefinition<Key> {
    return defineKind('cohort', key, body)
}

import { TopicMessage } from '../../kafka/producer'
import { InternalPerson } from '../../types'

export type MoveDistinctIdsResult =
    | { readonly success: true; readonly messages: TopicMessage[]; readonly distinctIdsMoved: string[] }
    | { readonly success: false; readonly error: 'TargetNotFound' }
    | { readonly success: false; readonly error: 'SourceNotFound' }

export type CreatePersonResult =
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: TopicMessage[]
          readonly created: true
      }
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: TopicMessage[]
          readonly created: false
      }
    | { readonly success: false; readonly error: 'CreationConflict'; readonly distinctIds: string[] }
    | { readonly success: false; readonly error: 'PropertiesSizeViolation'; readonly distinctIds: string[] }

export interface PersonPropertiesSize {
    total_props_bytes: number
}

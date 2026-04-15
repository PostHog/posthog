import { InternalPerson } from '../../types'
import { PersonMessage } from '../../worker/ingestion/persons/person-message'

export type MoveDistinctIdsResult =
    | { readonly success: true; readonly messages: PersonMessage[]; readonly distinctIdsMoved: string[] }
    | { readonly success: false; readonly error: 'TargetNotFound' }
    | { readonly success: false; readonly error: 'SourceNotFound' }

export type CreatePersonResult =
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: PersonMessage[]
          readonly created: true
      }
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: PersonMessage[]
          readonly created: false
      }
    | { readonly success: false; readonly error: 'CreationConflict'; readonly distinctIds: string[] }
    | { readonly success: false; readonly error: 'PropertiesSizeViolation'; readonly distinctIds: string[] }

export interface PersonPropertiesSize {
    total_props_bytes: number
}

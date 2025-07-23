import { InternalPerson } from '../../../types'

export interface PersonRepository {
    fetchPerson(
        teamId: number,
        distinctId: string,
        options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined>
}

import { HogFlow, isRowScopedTrigger } from '~/cdp/schema/hogflow'
import { hasPushActions } from '~/cdp/services/hogflows/hogflow-utils'
import type { PersonsManagerService } from '~/cdp/services/managers/persons-manager.service'
import { CyclotronJobInvocationHogFlow, CyclotronPerson } from '~/cdp/types'

export type HogFlowPersonLookup = {
    id: string
    kind: 'distinct_id' | 'person_id'
    forceFresh: boolean
}

type PersonReader = Pick<PersonsManagerService, 'getCyclotronPerson'>

type HogFlowState = CyclotronJobInvocationHogFlow['state']

// The matcher wrote this job's personId anchor: a merge repointed the distinct_id onto a
// survivor, or the distinct_id acquired its first person. Resolve by that personId so the step
// reads the right person — resolving by the distinct_id would hit its stale ~1min cache entry
// (the pre-merge person, or none at all) and e.g. drop an email.
export const resolvesByRepointedPerson = (state: HogFlowState): boolean =>
    state.personIdRepointed === true && !!state.personId

export function hogFlowPersonLookup(hogFlow: HogFlow, state: HogFlowState): HogFlowPersonLookup | null {
    // Row-scoped invocations (a warehouse row, a Slack message, a GitHub event) don't have
    // a real person — the delivery is the unit of work and person-dependent steps no-op for
    // these flows. Explicitly skip the person lookup rather than relying on
    // event.distinct_id being empty so future changes to the synthetic event shape don't
    // accidentally re-enable the lookup.
    const isRowScoped = isRowScopedTrigger(hogFlow.trigger)
    // Account-audience batch invocations carry the account's group key as
    // event.distinct_id; resolving it as a person distinct_id would attach an
    // unrelated person to the run. Accounts have no person — skip the lookup.
    // The state stamp wins over the live trigger, which may have been edited to a
    // person audience while these children were queued; the trigger check remains
    // as a fallback for jobs enqueued before the stamp existed.
    const isAccountAudience =
        state.accountAudience === true ||
        (hogFlow.trigger?.type === 'batch' && hogFlow.trigger.filters?.audience_type === 'accounts')
    if (isRowScoped || isAccountAudience) {
        return null
    }
    const byRepointedPerson = resolvesByRepointedPerson(state)
    const id = byRepointedPerson ? state.personId : state.event.distinct_id || state.personId
    if (!id) {
        return null
    }
    return {
        id,
        kind: byRepointedPerson || !state.event.distinct_id ? 'person_id' : 'distinct_id',
        // A push cannot be recalled, and the cached person can predate a device that
        // unregistered since the last read, so a flow that sends push bypasses the cache here.
        // A wait woken by a match advances without re-evaluating, so the steps after it would
        // otherwise read the person cached when the wait parked, without the write that woke it.
        forceFresh: hasPushActions(hogFlow.actions) || state.currentAction?.eventMatched === true,
    }
}

// A transactional email's caller holds only a send key, which grants no access to person data, so its
// template never sees person properties, or the display name derived from them. The person stays attached
// so the send is recorded against them.
function personForFlow(hogFlow: HogFlow, person: CyclotronPerson | null): CyclotronPerson | undefined {
    if (!person) {
        return undefined
    }
    return hogFlow.trigger?.type === 'api' ? { ...person, properties: {}, name: '' } : person
}

export async function loadHogFlowPerson(
    persons: PersonReader,
    hogFlow: HogFlow,
    lookup: HogFlowPersonLookup
): Promise<CyclotronPerson | undefined> {
    const person = await persons.getCyclotronPerson(hogFlow.team_id, lookup.id, lookup.kind, {
        forceFresh: lookup.forceFresh,
    })
    return personForFlow(hogFlow, person)
}

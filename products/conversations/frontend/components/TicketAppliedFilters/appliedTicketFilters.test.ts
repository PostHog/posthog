import { type AppliedTicketFiltersState, listAppliedTicketFilters } from './appliedTicketFilters'

const emptyState: AppliedTicketFiltersState = {
    statusFilter: [],
    priorityFilter: [],
    channelFilter: 'all',
    slaFilter: 'all',
    aiTriageResultFilter: [],
    assigneeFilterEntries: [],
    tagsFilter: [],
    tagsMatch: 'any',
    tagsExcludeFilter: [],
}

describe('listAppliedTicketFilters', () => {
    it('returns no chips when every filter is at its default', () => {
        expect(listAppliedTicketFilters(emptyState)).toEqual([])
    })

    it('emits one chip per applied dimension so a missing kind cannot hide from the bar', () => {
        const chips = listAppliedTicketFilters({
            ...emptyState,
            statusFilter: ['open'],
            priorityFilter: ['high'],
            channelFilter: 'email',
            slaFilter: 'breached',
            aiTriageResultFilter: ['persisted'],
            assigneeFilterEntries: ['me'],
            tagsFilter: ['billing'],
            tagsMatch: 'all',
            tagsExcludeFilter: ['spam'],
        })

        expect(chips.map((chip) => chip.key)).toEqual([
            'status:open',
            'priority:high',
            'channel:email',
            'sla:breached',
            'ai:persisted',
            'tag:billing',
            'tag-exclude:spam',
            'assignee:me',
        ])
        expect(chips.find((chip) => chip.kind === 'status')).toMatchObject({ label: 'Status: Open' })
        expect(chips.find((chip) => chip.kind === 'tag')).toMatchObject({ label: 'Tag (all): billing' })
    })
})

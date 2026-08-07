import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPencil } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { MeetingApi, MeetingParticipantApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountMeetingsLogic, NOT_LOADED } from './accountMeetingsLogic'
import { AccountsEvents } from './constants'

// Matches the Support tickets tab, the other client-side-paginated account tab.
const PAGE_SIZE = 10
const COLLAPSED_ATTENDEE_COUNT = 3

function MatchingEditor({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountMeetingsLogic({ accountId })
    const { domainsDraft, emailsDraft, savingMatching } = useValues(logic)
    const { closeMatchingEditor, setDomainsDraft, setEmailsDraft, saveMatching } = useActions(logic)

    return (
        <div className="flex flex-col gap-2 border rounded p-3 bg-bg-light">
            <span className="text-xs text-secondary">
                Meetings with attendees at these domains or addresses match this account.
            </span>
            <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1 flex-1 min-w-56">
                    <span className="text-xs font-semibold text-secondary">Email domains</span>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        disableFiltering
                        size="small"
                        value={domainsDraft}
                        onChange={setDomainsDraft}
                        placeholder="acme.com"
                    />
                </div>
                <div className="flex flex-col gap-1 flex-1 min-w-56">
                    <span className="text-xs font-semibold text-secondary">Known emails</span>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        disableFiltering
                        size="small"
                        value={emailsDraft}
                        onChange={setEmailsDraft}
                        placeholder="jane@gmail.com"
                    />
                </div>
                <div className="flex flex-row gap-2 shrink-0">
                    <LemonButton size="small" type="secondary" onClick={closeMatchingEditor}>
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" onClick={saveMatching} loading={savingMatching}>
                        Save
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

function AttendeeLink({ participant }: { participant: MeetingParticipantApi }): JSX.Element {
    const label = participant.display_name || participant.email
    if (!participant.person_id) {
        return <span title={participant.email}>{label}</span>
    }
    return (
        <Link
            to={urls.personByUUID(participant.person_id)}
            title={participant.email}
            onClick={() => posthog.capture(AccountsEvents.MeetingAttendeeClicked)}
        >
            {label}
        </Link>
    )
}

function AttendeeList({ accountId, meeting }: { accountId: string; meeting: MeetingApi }): JSX.Element {
    const logic = accountMeetingsLogic({ accountId })
    const { expandedAttendeeMeetingIds } = useValues(logic)
    const { toggleAttendeesExpanded } = useActions(logic)

    const expanded = expandedAttendeeMeetingIds.includes(meeting.id)
    const shown = expanded ? meeting.participants : meeting.participants.slice(0, COLLAPSED_ATTENDEE_COUNT)
    const hiddenCount = meeting.participants.length - shown.length

    return (
        <span className="text-sm">
            {shown.map((participant, index) => (
                <span key={participant.email}>
                    <AttendeeLink participant={participant} />
                    {index < shown.length - 1 ? ', ' : ''}
                </span>
            ))}
            {hiddenCount > 0 && (
                <>
                    {', '}
                    <Link onClick={() => toggleAttendeesExpanded(meeting.id)}>+{hiddenCount} more</Link>
                </>
            )}
            {expanded && meeting.participants.length > COLLAPSED_ATTENDEE_COUNT && (
                <>
                    {' '}
                    <Link onClick={() => toggleAttendeesExpanded(meeting.id)}>show less</Link>
                </>
            )}
        </span>
    )
}

function MeetingsEmptyState({ title, detail }: { title: string; detail: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <BigLeaguesHog className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
        </div>
    )
}

const STATUS_TAG_TYPE = {
    confirmed: 'success',
    tentative: 'default',
    cancelled: 'danger',
} as const

export function AccountMeetingsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountMeetingsLogic({ accountId })
    const { meetingsResult, meetingsResultLoading, filteredMeetings, searchTerm, matchingEditorOpen } = useValues(logic)
    const { setSearchTerm, openMatchingEditor } = useActions(logic)

    if (meetingsResultLoading || meetingsResult === NOT_LOADED) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { meetings, loadFailed } = meetingsResult

    const columns: LemonTableColumns<MeetingApi> = [
        {
            title: 'Meeting',
            key: 'title',
            render: (_, meeting) =>
                meeting.title ? (
                    <span className="font-medium line-clamp-1">{meeting.title}</span>
                ) : (
                    <span className="text-muted italic">Untitled meeting</span>
                ),
        },
        {
            title: 'When',
            key: 'start_time',
            width: 140,
            render: (_, meeting) => <TZLabel time={meeting.start_time} />,
            sorter: (a, b) => a.start_time.localeCompare(b.start_time),
        },
        {
            title: 'Attendees',
            key: 'participants',
            render: (_, meeting) => <AttendeeList accountId={accountId} meeting={meeting} />,
        },
        {
            title: 'Status',
            key: 'status',
            width: 100,
            render: (_, meeting) => (
                <LemonTag type={STATUS_TAG_TYPE[meeting.status as keyof typeof STATUS_TAG_TYPE] ?? 'default'}>
                    {meeting.status}
                </LemonTag>
            ),
        },
    ]

    let content: JSX.Element
    if (loadFailed) {
        content = (
            <MeetingsEmptyState
                title="Couldn't load meetings"
                detail="Something went wrong loading this account's meetings. Try refreshing the page."
            />
        )
    } else if (!meetings || meetings.length === 0) {
        content = (
            <MeetingsEmptyState
                title="No meetings yet"
                detail="Meetings from connected Google Calendars that include people from this account show up here. Use 'Edit matching' to add the email domains and addresses that identify this account."
            />
        )
    } else {
        content = (
            <LemonTable<MeetingApi>
                size="small"
                embedded
                dataSource={filteredMeetings}
                columns={columns}
                rowKey="id"
                pagination={{ pageSize: PAGE_SIZE }}
                emptyState="No meetings match your search."
            />
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search by meeting or attendee..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    size="small"
                    className="min-w-64"
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPencil />}
                    active={matchingEditorOpen}
                    data-attr="edit-meeting-matching"
                    onClick={openMatchingEditor}
                >
                    Edit matching
                </LemonButton>
            </div>
            {matchingEditorOpen && <MatchingEditor accountId={accountId} />}
            {content}
        </div>
    )
}

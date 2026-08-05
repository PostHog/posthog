import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonDropdown,
    LemonInputSelect,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { TZLabel } from 'lib/components/TZLabel'

import { MeetingApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountMeetingsLogic, NOT_LOADED } from './accountMeetingsLogic'

// Matches the Support tickets tab, the other client-side-paginated account tab.
const PAGE_SIZE = 10

function EditMeetingMatchingButton({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountMeetingsLogic({ accountId })
    const { matchingEditorOpen, domainsDraft, emailsDraft, savingMatching } = useValues(logic)
    const { openMatchingEditor, closeMatchingEditor, setDomainsDraft, setEmailsDraft, saveMatching } = useActions(logic)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={matchingEditorOpen}
            onVisibilityChange={(visible) => {
                if (!visible) {
                    closeMatchingEditor()
                }
            }}
            showArrow
            overlay={
                <div className="flex flex-col gap-2 w-80">
                    <span className="text-xs text-secondary">
                        Meetings with attendees at these domains or addresses match this account.
                    </span>
                    <div className="flex flex-col gap-1">
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
                    <div className="flex flex-col gap-1">
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
                    <LemonDivider className="my-1" />
                    <div className="flex flex-row gap-2 justify-end">
                        <LemonButton size="xsmall" type="secondary" onClick={closeMatchingEditor}>
                            Cancel
                        </LemonButton>
                        <LemonButton size="xsmall" type="primary" onClick={saveMatching} loading={savingMatching}>
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconPencil />}
                data-attr="edit-meeting-matching"
                onClick={openMatchingEditor}
            >
                Edit matching
            </LemonButton>
        </LemonDropdown>
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
        render: (_, meeting) => (
            <span className="line-clamp-1 text-sm">
                {meeting.participants.map((participant) => participant.display_name || participant.email).join(', ')}
            </span>
        ),
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

export function AccountMeetingsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { meetingsResult, meetingsResultLoading } = useValues(accountMeetingsLogic({ accountId }))

    if (meetingsResultLoading || meetingsResult === NOT_LOADED) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { meetings, loadFailed } = meetingsResult

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
                dataSource={meetings}
                columns={columns}
                rowKey="id"
                pagination={{ pageSize: PAGE_SIZE }}
            />
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-end">
                <EditMeetingMatchingButton accountId={accountId} />
            </div>
            {content}
        </div>
    )
}

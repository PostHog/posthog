import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter, fullName } from 'lib/utils/strings'

import type { MemberProjectAccessEntryApi } from 'products/access_control/frontend/generated/api.schemas'

import { describeProjectAccessSource, projectAccessSourceUrl } from './memberProjectAccess'
import { memberProjectAccessLogic } from './memberProjectAccessLogic'

export function MemberProjectAccessModal(): JSX.Element {
    const { modalMember, modalProjects, projectAccessLoading } = useValues(memberProjectAccessLogic)
    const { closeProjectAccessModal } = useActions(memberProjectAccessLogic)

    const columns: LemonTableColumns<MemberProjectAccessEntryApi> = [
        {
            title: 'Project',
            key: 'team_name',
            render: (_, entry) => <span className="font-medium">{entry.team_name}</span>,
        },
        {
            title: 'Access',
            key: 'access_level',
            render: (_, entry) => (
                <div className="flex flex-col py-1">
                    <span>
                        {entry.access_level === 'none' ? 'No access' : capitalizeFirstLetter(entry.access_level)}
                    </span>
                    <span className="text-xs text-tertiary">{describeProjectAccessSource(entry)}</span>
                </div>
            ),
        },
        {
            key: 'manage',
            width: 0,
            render: (_, entry) => {
                const url = modalMember ? projectAccessSourceUrl(entry, modalMember.id) : null
                return url ? (
                    <LemonButton type="secondary" size="small" to={url} data-attr="member-project-access-manage">
                        Manage
                    </LemonButton>
                ) : null
            },
        },
    ]

    return (
        <LemonModal
            isOpen={!!modalMember}
            onClose={closeProjectAccessModal}
            title={modalMember ? `Project access for ${fullName(modalMember.user)}` : ''}
            description={
                <>
                    Access is set per project in the access control settings.{' '}
                    <Link to="https://posthog.com/docs/settings/access-control" target="_blank">
                        Docs
                    </Link>
                </>
            }
            width={720}
        >
            <LemonTable
                dataSource={modalProjects ?? []}
                columns={columns}
                rowKey="team_id"
                loading={projectAccessLoading}
                emptyState="You don't have access to any of the projects this member could be in."
                data-attr="member-project-access-table"
            />
        </LemonModal>
    )
}

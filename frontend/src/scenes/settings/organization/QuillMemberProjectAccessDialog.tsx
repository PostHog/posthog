import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import {
    Badge,
    Button,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { ProjectFreshnessIndicator } from 'lib/components/Account/ProjectFreshnessIndicator'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter, fullNameOrEmail } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'

import type { MemberProjectAccessEntryApi } from 'products/access_control/frontend/generated/api.schemas'

import { describeProjectAccessSource, projectAccessSourceUrl } from './memberProjectAccess'
import { memberProjectAccessLogic } from './memberProjectAccessLogic'

export function QuillMemberProjectAccessDialog(): JSX.Element {
    const { modalMember, modalProjects, projectAccessLoading } = useValues(memberProjectAccessLogic)
    const { closeProjectAccessModal } = useActions(memberProjectAccessLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const columns: ColumnDef<MemberProjectAccessEntryApi>[] = [
        {
            id: 'team_name',
            header: 'Project',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row }) => {
                const entry = row.original
                const team = currentOrganization?.teams.find((t) => t.id === entry.team_id)

                return (
                    <div className="flex flex-col items-start gap-0.5">
                        <span className="flex items-center gap-2">
                            <Text size="xs" weight="medium" render={<span />} className="m-0 truncate">
                                {team?.name ?? entry.team_name}
                            </Text>
                            {team?.is_demo ? <Badge>Demo</Badge> : null}
                        </span>
                        <ProjectFreshnessIndicator teamId={entry.team_id} className="ml-0" />
                    </div>
                )
            },
        },
        {
            id: 'access_level',
            header: 'Access',
            enableSorting: false,
            cell: ({ row }) => {
                const entry = row.original

                return (
                    <div className="flex flex-col gap-0.5">
                        <Text size="xs" render={<span />} className="m-0">
                            {entry.access_level === 'none' ? 'No access' : capitalizeFirstLetter(entry.access_level)}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />} className="m-0">
                            {modalMember ? describeProjectAccessSource(entry, modalMember.level) : null}
                        </Text>
                    </div>
                )
            },
        },
        {
            id: 'manage',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => {
                const url = modalMember ? projectAccessSourceUrl(row.original, modalMember.id) : null

                return url ? (
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={<LinkPrimitive to={url} />}
                        data-attr="member-project-access-manage"
                    >
                        Manage
                    </Button>
                ) : null
            },
        },
    ]

    return (
        <Dialog
            open={!!modalMember}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeProjectAccessModal()
                }
            }}
        >
            <DialogContent size="wide" className="max-w-180">
                <DialogHeader>
                    <DialogTitle>
                        {modalMember ? `Project access for ${fullNameOrEmail(modalMember.user)}` : ''}
                    </DialogTitle>
                    <DialogDescription>
                        Access is set per project in the access control settings.{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={
                                <LinkPrimitive to="https://posthog.com/docs/settings/access-control" target="_blank" />
                            }
                        >
                            Docs
                        </Button>
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {projectAccessLoading && !modalProjects ? (
                        <div className="flex flex-col gap-2">
                            <Skeleton className="h-10" />
                            <Skeleton className="h-10" />
                        </div>
                    ) : (
                        <div data-attr="member-project-access-table">
                            <DataTable
                                columns={columns}
                                data={modalProjects ?? []}
                                fullWidth
                                getRowId={(entry) => String(entry.team_id)}
                                empty={
                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                        You don't have access to any of the projects this member could be in.
                                    </Text>
                                }
                            />
                        </div>
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

import type { ColumnDef, RowSelectionState } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBell, IconDashboard, IconGraph, IconLetter, IconLock, IconNotebook, IconRewindPlay } from '@posthog/icons'
import {
    Button,
    DataTable,
    Heading,
    Spinner,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { IconMicrosoftTeams, IconSlack } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { MemberOffboardingResourceApi } from 'products/platform_features/frontend/generated/api.schemas'
import { subscriptionDestination } from 'products/subscriptions/frontend/scenes/components/subscriptionDestination'

import { memberOffboardingLogic } from './memberOffboardingLogic'

const PAGE_SIZE = 5

const DESTINATION_ICONS: Record<string, JSX.Element> = {
    email: <IconLetter />,
    slack: <IconSlack />,
    teams: <IconMicrosoftTeams />,
}

const RESOURCE_ICONS = {
    dashboard: <IconDashboard />,
    insight: <IconGraph />,
    notebook: <IconNotebook />,
    recording: <IconRewindPlay />,
    subscription: <IconBell />,
    alert: <IconBell />,
}

function ResourceKindIcon({ resource }: { resource: MemberOffboardingResourceApi }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        className="inline-flex shrink-0 text-lg text-muted-foreground"
                        role="img"
                        aria-label={resource.destination_type ?? resource.kind}
                        tabIndex={resource.destination_type ? 0 : undefined}
                    />
                }
            >
                {resource.destination_type
                    ? (DESTINATION_ICONS[resource.destination_type] ?? <IconBell />)
                    : RESOURCE_ICONS[resource.kind]}
            </TooltipTrigger>
            <TooltipContent>
                {resource.destination_type ? (
                    <div className="flex flex-col">
                        {subscriptionDestination(resource.destination_type, resource.destination ?? '').parts.map(
                            (recipient, index) => (
                                <span key={index}>{recipient}</span>
                            )
                        )}
                    </div>
                ) : (
                    resource.kind
                )}
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillMemberOffboardingResourceSection({
    resources,
    kind,
    isSelf,
    disabledReason,
}: {
    resources: MemberOffboardingResourceApi[]
    kind: 'public' | 'subscriptions'
    isSelf: boolean
    disabledReason: string | undefined
}): JSX.Element {
    const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
    const { keep, savingResourceIds, getSelectionLabel } = useValues(memberOffboardingLogic)
    const { setKeep, disableResources, openTransfer } = useActions(memberOffboardingLogic)

    const isSubscription = kind === 'subscriptions'
    const selectedIds = resources.filter((resource) => rowSelection[resource.id]).map((resource) => resource.id)

    const disableSelected = (): void => {
        disableResources(selectedIds)
        setRowSelection({})
    }

    const transferSelected = (): void => {
        openTransfer(selectedIds)
        setRowSelection({})
    }

    const columns: ColumnDef<MemberOffboardingResourceApi>[] = [
        {
            id: 'name',
            header: isSubscription ? 'Name' : 'Resource name',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row }) => (
                <div className="flex min-w-0 items-center gap-2">
                    <ResourceKindIcon resource={row.original} />
                    <Button
                        variant="link-foreground"
                        size="sm"
                        nativeButton={false}
                        className="max-w-full"
                        render={<LinkPrimitive to={row.original.url ?? undefined} target="_blank" />}
                        data-attr="offboarding-resource-link"
                    >
                        <span className="truncate">{row.original.name}</span>
                    </Button>
                </div>
            ),
        },
        {
            id: 'project',
            header: 'Project',
            enableSorting: false,
            cell: ({ row }) => (
                <Text size="xs" render={<span />} className="m-0 break-words">
                    {row.original.project_name}
                </Text>
            ),
        },
        ...(isSubscription
            ? [
                  {
                      id: 'created_at',
                      header: 'Created on',
                      enableSorting: false,
                      cell: ({ row }: { row: { original: MemberOffboardingResourceApi } }) =>
                          row.original.created_at ? (
                              <TZLabel time={row.original.created_at} />
                          ) : (
                              <Text size="xs" variant="muted" render={<span />} className="m-0">
                                  Unknown
                              </Text>
                          ),
                  } satisfies ColumnDef<MemberOffboardingResourceApi>,
              ]
            : []),
        ...(!isSelf
            ? [
                  {
                      id: 'disable',
                      header: isSubscription ? 'Enabled' : 'Publicly shared',
                      enableSorting: false,
                      cell: ({ row }: { row: { original: MemberOffboardingResourceApi } }) => {
                          const resource = row.original

                          return (
                              <div className="flex items-center gap-2">
                                  <Switch
                                      checked={keep.includes(resource.id)}
                                      onCheckedChange={(enabled: boolean) => setKeep(resource.id, enabled)}
                                      disabledReason={disabledReason}
                                      aria-label={`${isSubscription ? 'Enable' : 'Public sharing for'} ${resource.name}`}
                                      data-attr={
                                          isSubscription
                                              ? 'offboarding-disable-subscription'
                                              : 'offboarding-disable-dashboard'
                                      }
                                  />
                                  {savingResourceIds.includes(resource.id) && <Spinner />}
                                  {resource.password_protected && (
                                      <Tooltip>
                                          <TooltipTrigger
                                              render={
                                                  <span
                                                      className="flex text-muted-foreground"
                                                      role="img"
                                                      aria-label="Password protected"
                                                  />
                                              }
                                          >
                                              <IconLock />
                                          </TooltipTrigger>
                                          <TooltipContent>Password protected</TooltipContent>
                                      </Tooltip>
                                  )}
                              </div>
                          )
                      },
                  } satisfies ColumnDef<MemberOffboardingResourceApi>,
              ]
            : []),
    ]

    return (
        <section className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                {isSubscription ? 'Subscriptions and alerts' : 'Publicly shared resources'}
            </Heading>
            <Text size="xs" render={<p className="m-0" />}>
                {isSubscription
                    ? 'These subscriptions and alerts will be disabled at their next run after this member leaves. Transfer ownership to keep them running, or disable them now.'
                    : "These resources were shared by this member and are accessible to anyone with the link. You can disable public sharing. This won't delete them."}
            </Text>
            {!isSelf && (
                <div className="flex min-h-9 flex-wrap items-center gap-2">
                    {selectedIds.length > 0 ? (
                        <>
                            {isSubscription && (
                                <Button variant="outline" disabledReason={disabledReason} onClick={transferSelected}>
                                    Transfer ownership
                                </Button>
                            )}
                            <Button
                                variant="destructive-outline"
                                loading={resources.some((resource) => savingResourceIds.includes(resource.id))}
                                disabledReason={disabledReason}
                                onClick={disableSelected}
                            >
                                Disable selected
                            </Button>
                            <Text size="xs" variant="muted" render={<span />} className="m-0 min-w-0 truncate">
                                {getSelectionLabel(selectedIds)}
                            </Text>
                        </>
                    ) : (
                        <Text size="xs" variant="muted" render={<span />} className="m-0 min-w-0 truncate">
                            {getSelectionLabel(resources.map((resource) => resource.id))}
                        </Text>
                    )}
                </div>
            )}
            <DataTable
                columns={columns}
                data={resources}
                fullWidth
                size="sm"
                getRowId={(resource) => resource.id}
                selectable={!isSelf}
                rowSelection={rowSelection}
                onRowSelectionChange={setRowSelection}
                rowSelectionLabel={(resource) => `Select ${resource.name}`}
                rowSelectionDisabledReason={() => disabledReason ?? null}
                pageSize={resources.length > PAGE_SIZE ? PAGE_SIZE : undefined}
            />
        </section>
    )
}

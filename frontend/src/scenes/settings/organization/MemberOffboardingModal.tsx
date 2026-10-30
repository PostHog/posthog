import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDashboard, IconGraph, IconLock, IconNotebook, IconRewindPlay } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { fullNameOrEmail } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { memberOffboardingLogic } from './memberOffboardingLogic'

const RESOURCE_ICONS = {
    dashboard: <IconDashboard />,
    insight: <IconGraph />,
    notebook: <IconNotebook />,
    recording: <IconRewindPlay />,
}

export function MemberOffboardingModal(): JSX.Element {
    const [bulkBarTarget, setBulkBarTarget] = useState<HTMLDivElement | null>(null)
    const {
        member,
        resources,
        resourcesLoading,
        loadError,
        keep,
        removedLoading,
        savingResourcesLoading,
        getSelectionLabel,
    } = useValues(memberOffboardingLogic)
    const { close, loadResources, setKeep, disableResources, remove } = useActions(memberOffboardingLogic)
    const { scopedApiKeys, scopedApiKeysLoading } = useValues(membersLogic)
    const { user } = useValues(userLogic)
    const isSelf = member?.user.uuid === user?.uuid
    const busyReason = removedLoading ? 'Removing member…' : savingResourcesLoading ? 'Saving changes…' : undefined
    const hasResources = !resourcesLoading && !loadError && !!resources?.length

    return (
        <LemonModal
            isOpen={!!member}
            onClose={busyReason ? undefined : close}
            title={
                isSelf
                    ? 'Leave organization?'
                    : `Remove ${member ? fullNameOrEmail(member.user) : 'member'} from organization?`
            }
            width={hasResources ? 720 : 576}
            footer={
                <>
                    <LemonButton type="secondary" onClick={close} disabledReason={busyReason}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        loading={removedLoading}
                        disabledReason={
                            busyReason ||
                            (resourcesLoading
                                ? 'Checking public resources…'
                                : loadError || resources === null
                                  ? 'Load the resource review before continuing'
                                  : undefined)
                        }
                        onClick={remove}
                        data-attr="confirm-org-member-offboarding"
                    >
                        {isSelf ? 'Leave' : 'Remove'}
                    </LemonButton>
                </>
            }
        >
            <p>
                {isSelf
                    ? 'Are you sure you want to leave this organization? This cannot be undone. If you leave, you will no longer have access to this organization.'
                    : 'The user will no longer have access to this organization.'}
            </p>
            {resourcesLoading ? (
                <LemonSkeleton className="h-12" />
            ) : loadError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadResources }}>
                    Couldn't load public resources. Retry before continuing.
                </LemonBanner>
            ) : hasResources ? (
                <section className="space-y-3">
                    <h3>Publicly shared resources</h3>
                    <p>
                        These resources were shared by this member and are accessible to anyone with the link. You can
                        disable public sharing. This won't delete them. Changes apply immediately, even if you cancel.
                    </p>
                    {!isSelf && (
                        <div className="relative h-9">
                            <div ref={setBulkBarTarget} className="absolute inset-0 [&:not(:empty)+span]:hidden" />
                            <span className="flex h-full items-center text-secondary text-sm">
                                {getSelectionLabel(resources!.map((resource) => resource.id))}
                            </span>
                        </div>
                    )}
                    <LemonTable
                        dataSource={resources ?? []}
                        rowKey="id"
                        bulkSelection={
                            isSelf
                                ? undefined
                                : {
                                      getKey: (resource) => resource.id,
                                      noun: ['resource', 'resources'],
                                      rowAriaLabel: (resource) => `Select ${resource.name}`,
                                      headerAriaLabel: 'Select all resources on this page',
                                      clearSelectionKey: member?.user.uuid,
                                      isRowSelectable: () => (busyReason ? { disabledReason: busyReason } : true),
                                      barPortalTarget: bulkBarTarget,
                                      actionsPlacement: 'start',
                                      barClassName: 'justify-start! px-0! [&>span]:min-w-0 [&>span]:truncate',
                                      getSelectionLabel: ({ selectedKeys }) => getSelectionLabel(selectedKeys),
                                      renderActions: (ctx) => (
                                          <LemonButton
                                              type="secondary"
                                              status="danger"
                                              size="small"
                                              loading={savingResourcesLoading}
                                              disabledReason={busyReason}
                                              onClick={() => {
                                                  disableResources([...ctx.selectedKeys])
                                                  ctx.clearSelection()
                                              }}
                                          >
                                              Disable selected
                                          </LemonButton>
                                      ),
                                  }
                        }
                        pagination={resources!.length > 5 ? { pageSize: 5 } : undefined}
                        columns={[
                            {
                                title: 'Resource name',
                                key: 'name',
                                render: (_, resource) => (
                                    <div className="flex items-center gap-2 min-w-0">
                                        <span
                                            className="text-lg text-secondary shrink-0"
                                            role="img"
                                            aria-label={resource.kind}
                                            title={resource.kind}
                                        >
                                            {RESOURCE_ICONS[resource.kind]}
                                        </span>
                                        <Link
                                            to={resource.url ?? undefined}
                                            target="_blank"
                                            targetBlankIcon={false}
                                            className="break-words min-w-0"
                                            data-attr="offboarding-resource-link"
                                        >
                                            {resource.name}
                                        </Link>
                                    </div>
                                ),
                            },
                            {
                                title: 'Project',
                                dataIndex: 'project_name',
                                key: 'project',
                                width: 124,
                                render: (name) => <span className="break-words">{name}</span>,
                            },
                            ...(!isSelf
                                ? [
                                      {
                                          title: 'Publicly shared',
                                          key: 'disable',
                                          width: 112,
                                          render: (_: unknown, resource: NonNullable<typeof resources>[number]) => (
                                              <div className="flex items-center gap-2">
                                                  <LemonSwitch
                                                      loading={savingResourcesLoading}
                                                      checked={keep.includes(resource.id)}
                                                      onChange={(enabled) => setKeep(resource.id, enabled)}
                                                      disabledReason={busyReason}
                                                      aria-label={`Public sharing for ${resource.name}`}
                                                      data-attr="offboarding-disable-dashboard"
                                                  />
                                                  {resource.password_required && (
                                                      <Tooltip title="Password protected">
                                                          <span
                                                              className="flex text-secondary"
                                                              role="img"
                                                              aria-label="Password protected"
                                                          >
                                                              <IconLock />
                                                          </span>
                                                      </Tooltip>
                                                  )}
                                              </div>
                                          ),
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </section>
            ) : null}
            {!scopedApiKeysLoading && !!scopedApiKeys?.keys.length && (
                <div className="mt-4">
                    <LemonBanner type="warning" className="mb-2">
                        The following personal API keys will lose access to this organization and will stop working
                        immediately. Check any services that depend on them before continuing.
                    </LemonBanner>
                    <LemonTable
                        dataSource={scopedApiKeys.keys}
                        columns={[
                            { title: 'Name', dataIndex: 'name', key: 'name' },
                            {
                                title: 'Last used',
                                dataIndex: 'last_used_at',
                                key: 'last_used_at',
                                render: (lastUsed) => (lastUsed ? <TZLabel time={lastUsed} /> : 'Never'),
                            },
                        ]}
                    />
                </div>
            )}
        </LemonModal>
    )
}

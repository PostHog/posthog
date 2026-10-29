import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDashboard, IconGraph, IconLock, IconNotebook, IconRewindPlay, IconBell } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { userLogic } from 'scenes/userLogic'

import type { MemberOffboardingResourceApi } from 'products/platform_features/frontend/generated/api.schemas'

import { memberOffboardingLogic } from './memberOffboardingLogic'

const RESOURCE_ICONS = {
    dashboard: <IconDashboard />,
    insight: <IconGraph />,
    notebook: <IconNotebook />,
    recording: <IconRewindPlay />,
    subscription: <IconBell />,
}

export function MemberOffboardingResourceSection({
    resources,
    kind,
}: {
    resources: MemberOffboardingResourceApi[]
    kind: 'public' | 'subscriptions'
}): JSX.Element {
    const [bulkBarTarget, setBulkBarTarget] = useState<HTMLDivElement | null>(null)
    const { member, keep, removedLoading, getSelectionLabel } = useValues(memberOffboardingLogic)
    const { setKeep, disableResources } = useActions(memberOffboardingLogic)
    const { user } = useValues(userLogic)
    const isSelf = member?.user.uuid === user?.uuid
    const isSubscription = kind === 'subscriptions'
    return (
        <section className="space-y-3">
            <h3>{isSubscription ? 'Subscriptions' : 'Publicly shared resources'}</h3>
            <p>
                {isSubscription
                    ? 'These subscriptions were created by this member. You can disable them when removing the member. Their email will be removed from delivery recipients, including subscriptions you keep enabled.'
                    : "These resources were shared by this member and are accessible to anyone with the link. You can disable public sharing. This won't delete them."}
            </p>
            {!isSelf && (
                <div className="relative h-9">
                    <div ref={setBulkBarTarget} className="absolute inset-0 [&:not(:empty)+span]:hidden" />
                    <span className="flex h-full items-center text-secondary text-sm">
                        {getSelectionLabel(resources.map((resource) => resource.id))}
                    </span>
                </div>
            )}
            <LemonTable
                dataSource={resources}
                rowKey="id"
                bulkSelection={
                    isSelf
                        ? undefined
                        : {
                              getKey: (resource) => resource.id,
                              noun: isSubscription ? ['subscription', 'subscriptions'] : ['resource', 'resources'],
                              rowAriaLabel: (resource) => `Select ${resource.name}`,
                              headerAriaLabel: isSubscription
                                  ? 'Select all subscriptions on this page'
                                  : 'Select all resources on this page',
                              clearSelectionKey: member?.user.uuid,
                              isRowSelectable: () => (removedLoading ? { disabledReason: 'Removing member…' } : true),
                              barPortalTarget: bulkBarTarget,
                              actionsPlacement: 'start',
                              barClassName: 'justify-start px-0 [&>span]:min-w-0 [&>span]:truncate',
                              getSelectionLabel: ({ selectedKeys }) => getSelectionLabel(selectedKeys),
                              renderActions: (ctx) => (
                                  <LemonButton
                                      type="secondary"
                                      status="danger"
                                      size="small"
                                      disabledReason={removedLoading ? 'Removing member…' : undefined}
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
                pagination={resources.length > 5 ? { pageSize: 5 } : undefined}
                columns={[
                    {
                        title: isSubscription ? 'Subscription name' : 'Resource name',
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
                    ...(isSubscription
                        ? [
                              {
                                  title: 'Created on',
                                  key: 'created_at',
                                  width: 96,
                                  render: (_: unknown, resource: MemberOffboardingResourceApi) =>
                                      resource.created_at ? (
                                          <TZLabel time={resource.created_at} />
                                      ) : (
                                          <span className="text-secondary">Unknown</span>
                                      ),
                              },
                          ]
                        : []),
                    ...(!isSelf
                        ? [
                              {
                                  title: isSubscription ? 'Enabled' : 'Publicly shared',
                                  key: 'disable',
                                  width: 112,
                                  render: (_: unknown, resource: MemberOffboardingResourceApi) => (
                                      <div className="flex items-center gap-2">
                                          <LemonSwitch
                                              checked={keep.includes(resource.id)}
                                              onChange={(enabled) => setKeep(resource.id, enabled)}
                                              disabledReason={removedLoading ? 'Removing member…' : undefined}
                                              aria-label={`${isSubscription ? 'Enable subscription' : 'Public sharing for'} ${resource.name}`}
                                              data-attr={
                                                  isSubscription
                                                      ? 'offboarding-disable-subscription'
                                                      : 'offboarding-disable-dashboard'
                                              }
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
            {isSelf && (
                <p>
                    {isSubscription
                        ? 'These subscriptions will be disabled when you leave.'
                        : 'Public sharing will be disabled for these resources when you leave.'}
                </p>
            )}
        </section>
    )
}

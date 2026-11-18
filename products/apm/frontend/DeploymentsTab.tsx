import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { formatChange } from './deploymentsDisplay'
import { deploymentsLogic } from './deploymentsLogic'
import type { DeploymentVersionApi } from './generated/api.schemas'
import { formatMs, formatPercent } from './healthDisplay'

export function DeploymentsTab(): JSX.Element {
    const {
        deployments,
        deploymentsLoading,
        deploymentsLoadError,
        deploymentsService,
        serviceNames,
        versionsNewestFirst,
        servicesHealthLoading,
        hasLoadError,
    } = useValues(deploymentsLogic)
    const { setDeploymentsService, requestReload } = useActions(deploymentsLogic)
    const servicesFailed = hasLoadError && !deploymentsService
    const servicesPending = servicesHealthLoading && !deploymentsService
    let emptyState = 'No versions in this time range. Set service.version on your spans to see deployments.'
    if (servicesFailed) {
        emptyState = "Couldn't load services."
    } else if (servicesPending) {
        emptyState = 'Loading services.'
    } else if (deploymentsService && !deployments) {
        emptyState = 'Loading versions.'
    }

    const columns: LemonTableColumns<DeploymentVersionApi> = [
        {
            title: 'Version',
            key: 'version',
            render: (_, row) => (
                <span className="flex items-center gap-2">
                    <span className="font-mono font-semibold">{row.version}</span>
                    {row.active && (
                        <LemonTag type="success" size="small">
                            Active
                        </LemonTag>
                    )}
                </span>
            ),
        },
        {
            title: 'First seen',
            key: 'first_seen',
            render: (_, row) => <TZLabel time={row.first_seen} />,
        },
        {
            title: 'Last seen',
            key: 'last_seen',
            render: (_, row) => <TZLabel time={row.last_seen} />,
        },
        {
            title: 'Requests',
            key: 'requests',
            align: 'right',
            render: (_, row) => <span className="font-mono">{row.requests.toLocaleString()}</span>,
        },
        {
            title: 'Error rate',
            key: 'error_rate',
            align: 'right',
            render: (_, row) => (
                <span className="font-mono">
                    {formatPercent(row.error_rate)}
                    <ChangeNote text={formatChange('error', row)} bad={(row.error_rate_change ?? 0) > 0} />
                </span>
            ),
        },
        {
            title: 'p95',
            key: 'p95_ms',
            align: 'right',
            render: (_, row) => (
                <span className="font-mono">
                    {formatMs(row.p95_ms)}
                    <ChangeNote text={formatChange('p95', row)} bad={(row.p95_change_pct ?? 0) > 0} />
                </span>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            {servicesFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => requestReload(), 'data-attr': 'apm-deployments-retry' }}
                >
                    Couldn't load services, so there's no service to show versions for.
                </LemonBanner>
            ) : (
                deploymentsLoadError && (
                    <LemonBanner type="error">Couldn't load versions. Try again shortly.</LemonBanner>
                )
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={deploymentsService}
                    onChange={(value) => setDeploymentsService(value)}
                    options={serviceNames.map((name) => ({ value: name, label: name }))}
                    placeholder="Pick a service"
                    data-attr="apm-deployments-service"
                />
                <span className="text-xs text-secondary">
                    One row per service.version seen in the time range. Changes compare with the version before it.
                </span>
            </div>
            <LemonTable
                columns={columns}
                dataSource={versionsNewestFirst}
                rowKey="version"
                loading={deploymentsLoading || servicesPending}
                emptyState={emptyState}
                data-attr="apm-deployments-table"
            />
        </div>
    )
}

function ChangeNote({ text, bad }: { text: string | null; bad: boolean }): JSX.Element | null {
    return text ? <span className={`ml-2 text-xs ${bad ? 'text-danger' : 'text-success'}`}>{text}</span> : null
}

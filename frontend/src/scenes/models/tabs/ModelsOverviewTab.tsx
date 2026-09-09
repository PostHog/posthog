import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { checkDisplayName } from 'products/data_quality/frontend/checksConstants'
import { CheckStatusCell } from 'products/data_quality/frontend/CheckStatusCell'
import { DataQualityOverviewCheckApi } from 'products/data_quality/frontend/generated/api.schemas'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { AttentionModel, modelsSceneLogic } from '../modelsSceneLogic'

function Section({
    title,
    description,
    action,
    children,
}: {
    title: string
    description: string
    action?: JSX.Element
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h3 className="mb-0">{title}</h3>
                    <p className="mb-0 text-secondary text-sm">{description}</p>
                </div>
                {action}
            </div>
            {children}
        </div>
    )
}

/** What the failure holds up, so a reader can tell a leaf model from one the whole graph waits on. */
function ImpactCell({ row }: { row: AttentionModel }): JSX.Element {
    if (row.downstreamCount === 0) {
        return <span className="text-secondary whitespace-nowrap">Nothing downstream</span>
    }
    return (
        <div className="flex flex-col whitespace-nowrap">
            <span>{pluralize(row.downstreamCount, 'model')} downstream</span>
            {row.skippedCount > 0 && (
                <span className="text-secondary text-xs">{pluralize(row.skippedCount, 'model')} skipped</span>
            )}
        </div>
    )
}

const ATTENTION_COLUMNS: LemonTableColumns<AttentionModel> = [
    {
        title: 'Model',
        key: 'name',
        render: (_, row) => <LemonTableLink to={urls.nodeDetail(row.node.id)} title={row.node.name} />,
    },
    {
        title: 'Problem',
        key: 'problem',
        width: 0,
        render: (_, row) => (
            <LemonTag type={row.problem === 'Suspended' ? 'warning' : 'danger'}>{row.problem}</LemonTag>
        ),
    },
    {
        title: 'Error',
        key: 'reason',
        render: (_, row) =>
            row.reason ? (
                <Tooltip title={<div className="whitespace-pre-wrap font-mono text-xs">{row.reason}</div>}>
                    <span className="line-clamp-2 text-secondary text-xs">{row.reason}</span>
                </Tooltip>
            ) : (
                <span className="text-secondary">-</span>
            ),
    },
    {
        title: 'Impact',
        key: 'impact',
        width: 0,
        render: (_, row) => <ImpactCell row={row} />,
    },
]

const CHECK_COLUMNS: LemonTableColumns<DataQualityOverviewCheckApi> = [
    {
        title: 'Check',
        key: 'check',
        render: (_, check) => checkDisplayName(check),
    },
    {
        title: 'Subject',
        key: 'subject',
        render: (_, check) =>
            check.subject_node_id ? (
                <Link to={urls.nodeDetail(check.subject_node_id, 'tests')}>{check.subject_name}</Link>
            ) : (
                check.subject_name
            ),
    },
    {
        title: 'Status',
        key: 'status',
        width: 0,
        render: (_, check) => <CheckStatusCell check={check} />,
    },
]

function OverviewBody({
    failingChecks,
    checksLoading,
}: {
    failingChecks: DataQualityOverviewCheckApi[]
    checksLoading: boolean
}): JSX.Element {
    const { attentionModels, nodesLoading } = useValues(modelsSceneLogic)

    if (!nodesLoading && attentionModels.length === 0 && failingChecks.length === 0) {
        return (
            <div className="flex items-center gap-2" data-attr="models-overview-healthy">
                <IconCheckCircle className="text-success text-xl" />
                <span>Every model ran as scheduled and every check passed.</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            {(nodesLoading || attentionModels.length > 0) && (
                <Section
                    title="Models needing attention"
                    description="A failed model did not finish its last run. A suspended one has stopped running on its schedule after repeated failures."
                    action={
                        <Link to={urls.models('models')} data-attr="models-overview-all-models">
                            All models
                        </Link>
                    }
                >
                    <LemonTable
                        columns={ATTENTION_COLUMNS}
                        dataSource={attentionModels}
                        loading={nodesLoading}
                        rowKey={(row) => row.node.id}
                        size="small"
                        data-attr="models-overview-attention"
                    />
                </Section>
            )}
            {failingChecks.length > 0 && (
                <Section
                    title="Failing data quality checks"
                    description="Assertions your models did not hold up on their last run."
                    action={
                        <Link to={urls.models('data-quality')} data-attr="models-overview-all-checks">
                            All checks
                        </Link>
                    }
                >
                    <LemonTable
                        columns={CHECK_COLUMNS}
                        dataSource={failingChecks}
                        loading={checksLoading}
                        rowKey={(check) => check.id}
                        size="small"
                        data-attr="models-overview-failing-checks"
                    />
                </Section>
            )}
        </div>
    )
}

/** Split out so the checks request is only made where the tab exists. */
function OverviewWithChecks(): JSX.Element {
    const { checks, overviewLoading } = useValues(dataQualityOverviewLogic)

    return (
        <OverviewBody
            failingChecks={checks.filter((check) => check.last_status === 'failed' || check.last_status === 'errored')}
            checksLoading={overviewLoading}
        />
    )
}

export function ModelsOverviewTab(): JSX.Element {
    const { dataQualityTabEnabled } = useValues(modelsSceneLogic)

    return dataQualityTabEnabled ? <OverviewWithChecks /> : <OverviewBody failingChecks={[]} checksLoading={false} />
}

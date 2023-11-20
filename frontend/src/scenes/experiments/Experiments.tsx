import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic, getExperimentStatus } from './experimentsLogic'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Experiment, ExperimentsTabs, AvailableFeature, ProgressStatus, ProductKey } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Link } from 'lib/lemon-ui/Link'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { userLogic } from 'scenes/userLogic'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ExperimentsPayGate } from './ExperimentsPayGate'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { router } from 'kea-router'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { StatusTag } from './Experiment'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const {
        filteredExperiments,
        experimentsLoading,
        tab,
        searchTerm,
        shouldShowEmptyState,
        shouldShowProductIntroduction,
    } = useValues(experimentsLogic)
    const { setExperimentsTab, deleteExperiment, setSearchStatus, setSearchTerm } = useActions(experimentsLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const EXPERIMENTS_PRODUCT_DESCRIPTION =
        'A/B testing help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or if they are likely just a chance occurrence.'

    const getExperimentDuration = (experiment: Experiment): number | undefined => {
        return experiment.end_date
            ? dayjs(experiment.end_date).diff(dayjs(experiment.start_date), 'day')
            : experiment.start_date
            ? dayjs().diff(dayjs(experiment.start_date), 'day')
            : undefined
    }

    const columns: LemonTableColumns<Experiment> = [
        {
            title: normalizeColumnTitle('Name'),
            dataIndex: 'name',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            render: function Render(_, experiment: Experiment) {
                return (
                    <>
                        <Link to={experiment.id ? urls.experiment(experiment.id) : undefined}>
                            <span className="row-name">{stringWithWBR(experiment.name, 17)}</span>
                        </Link>
                        {experiment.description && (
                            <LemonMarkdown className="row-description" lowKeyHeadings>
                                {experiment.description}
                            </LemonMarkdown>
                        )}
                    </>
                )
            },
        },
        createdByColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        createdAtColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        {
            title: 'Duration',
            key: 'duration',
            render: function Render(_, experiment: Experiment) {
                const duration = getExperimentDuration(experiment)

                return <div>{duration !== undefined ? `${duration} day${duration !== 1 ? 's' : ''}` : '--'}</div>
            },
            sorter: (a, b) => {
                const durationA = getExperimentDuration(a) ?? -1
                const durationB = getExperimentDuration(b) ?? -1
                return durationA > durationB ? 1 : -1
            },
            align: 'right',
        },
        {
            title: 'Status',
            key: 'status',
            render: function Render(_, experiment: Experiment) {
                return <StatusTag experiment={experiment} />
            },
            align: 'center',
            sorter: (a, b) => {
                const statusA = getExperimentStatus(a)
                const statusB = getExperimentStatus(b)

                const score = {
                    draft: 1,
                    running: 2,
                    complete: 3,
                }
                return score[statusA] > score[statusB] ? 1 : -1
            },
        },
        {
            width: 0,
            render: function Render(_, experiment: Experiment) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    to={urls.experiment(`${experiment.id}`)}
                                    size="small"
                                    fullWidth
                                >
                                    View
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteExperiment(experiment.id as number)}
                                    data-attr={`experiment-${experiment.id}-dropdown-remove`}
                                    fullWidth
                                >
                                    Delete experiment
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader
                title={<div className="flex items-center">A/B testing</div>}
                buttons={
                    hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ? (
                        <LemonButton type="primary" data-attr="create-experiment" to={urls.experiment('new')}>
                            New experiment
                        </LemonButton>
                    ) : undefined
                }
                caption={
                    <>
                        <Link
                            data-attr="experiment-help"
                            to="https://posthog.com/docs/experiments/installation?utm_medium=in-product&utm_campaign=new-experiment"
                            target="_blank"
                        >
                            {' '}
                            Visit the guide
                        </Link>{' '}
                        to learn more.
                    </>
                }
                tabbedPage={hasAvailableFeature(AvailableFeature.EXPERIMENTATION)}
            />
            {hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ? (
                <>
                    <LemonTabs
                        activeKey={tab}
                        onChange={(newKey) => setExperimentsTab(newKey)}
                        tabs={[
                            { key: ExperimentsTabs.All, label: 'All experiments' },
                            { key: ExperimentsTabs.Yours, label: 'Your experiments' },
                            { key: ExperimentsTabs.Archived, label: 'Archived experiments' },
                        ]}
                    />
                    {(shouldShowEmptyState || shouldShowProductIntroduction) &&
                        (tab === ExperimentsTabs.Archived ? (
                            <ProductIntroduction
                                productName="A/B testing"
                                productKey={ProductKey.EXPERIMENTS}
                                thingName="archived experiment"
                                description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                                docsURL="https://posthog.com/docs/experiments"
                                isEmpty={shouldShowEmptyState}
                            />
                        ) : (
                            <ProductIntroduction
                                productName="A/B testing"
                                productKey={ProductKey.EXPERIMENTS}
                                thingName="experiment"
                                description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                                docsURL="https://posthog.com/docs/experiments"
                                action={() => router.actions.push(urls.experiment('new'))}
                                isEmpty={shouldShowEmptyState}
                                customHog={ExperimentsHog}
                            />
                        ))}
                    {!shouldShowEmptyState && (
                        <>
                            <div className="flex justify-between mb-4">
                                <LemonInput
                                    type="search"
                                    placeholder="Search experiments"
                                    onChange={setSearchTerm}
                                    value={searchTerm}
                                />
                                <div className="flex items-center gap-2">
                                    <span>
                                        <b>Status</b>
                                    </span>
                                    <LemonSelect
                                        onChange={(status) => {
                                            if (status) {
                                                setSearchStatus(status as ProgressStatus | 'all')
                                            }
                                        }}
                                        options={
                                            [
                                                { label: 'All', value: 'all' },
                                                { label: 'Draft', value: ProgressStatus.Draft },
                                                { label: 'Running', value: ProgressStatus.Running },
                                                { label: 'Complete', value: ProgressStatus.Complete },
                                            ] as { label: string; value: string }[]
                                        }
                                        value="all"
                                        dropdownMaxContentWidth
                                    />
                                </div>
                            </div>
                            <LemonTable
                                dataSource={filteredExperiments}
                                columns={columns}
                                rowKey="id"
                                loading={experimentsLoading}
                                defaultSorting={{
                                    columnKey: 'created_at',
                                    order: -1,
                                }}
                                noSortingCancellation
                                pagination={{ pageSize: 100 }}
                                nouns={['experiment', 'experiments']}
                                data-attr="experiment-table"
                            />
                        </>
                    )}
                </>
            ) : (
                <ExperimentsPayGate />
            )}
        </div>
    )
}

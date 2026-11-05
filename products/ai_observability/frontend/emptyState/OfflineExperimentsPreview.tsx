import './OfflineExperimentsPreview.scss'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTable, type LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

const EXPERIMENTS = [
    {
        id: 'baseline-gpt',
        prompt: 'Baseline prompt',
        model: 'GPT',
        accuracy: 82,
        helpfulness: 70,
        output: 'You can export your data from settings.',
        resultAccuracy: 0.8,
        resultHelpfulness: 0.6,
        reasoning: 'The answer is broadly correct, but does not explain the steps.',
    },
    {
        id: 'baseline-claude',
        prompt: 'Baseline prompt',
        model: 'Claude',
        accuracy: 88,
        helpfulness: 78,
        output: 'Open the data table and use the export option to download a CSV.',
        resultAccuracy: 0.9,
        resultHelpfulness: 0.8,
        reasoning: 'Includes the format and where to find the export option.',
    },
    {
        id: 'revised-gpt',
        prompt: 'Revised prompt',
        model: 'GPT',
        accuracy: 94,
        helpfulness: 88,
        output: 'Open the data table, select Export, and choose CSV. The download includes your filtered results.',
        resultAccuracy: 1,
        resultHelpfulness: 0.9,
        reasoning: 'Gives clear steps and explains which data is included.',
    },
    {
        id: 'revised-claude',
        prompt: 'Revised prompt',
        model: 'Claude',
        accuracy: 92,
        helpfulness: 96,
        output: 'Open the data table and apply your filters. Select Export, choose CSV, and download the file.',
        resultAccuracy: 0.9,
        resultHelpfulness: 1,
        reasoning: 'Walks through the complete workflow, including filtering first.',
    },
]

type PreviewExperiment = (typeof EXPERIMENTS)[number]

const columns: LemonTableColumns<PreviewExperiment> = [
    {
        title: 'Experiment',
        width: '44%',
        render: (_, experiment) => (
            <label
                htmlFor={`offline-experiments-preview-${experiment.id}`}
                className={`OfflineExperimentsPreview__choice OfflineExperimentsPreview__choice--${experiment.id}`}
            >
                <span className="OfflineExperimentsPreview__selection" aria-hidden="true" />
                <span className="min-w-0">
                    <span className="block font-semibold truncate">{experiment.prompt}</span>
                    <span className="block text-muted">{experiment.model}</span>
                </span>
            </label>
        ),
    },
    ...(['accuracy', 'helpfulness'] as const).map((scorer) => ({
        title: scorer === 'accuracy' ? 'Accuracy' : 'Helpfulness',
        key: scorer,
        width: '28%',
        render: (_: unknown, experiment: PreviewExperiment): JSX.Element => (
            <div className="space-y-1" aria-label={`${scorer}: ${experiment[scorer]}%`}>
                <span className="font-semibold tabular-nums">{experiment[scorer]}%</span>
                <LemonProgress
                    percent={experiment[scorer]}
                    strokeColor={scorer === 'accuracy' ? 'var(--offline-experiments-preview-accent)' : 'var(--success)'}
                    smoothing={false}
                />
            </div>
        ),
    })),
]

export function OfflineExperimentsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('OfflineExperimentsPreview', isStatic && 'OfflineExperimentsPreview--static')}>
            {EXPERIMENTS.map((experiment, index) => (
                <input
                    key={experiment.id}
                    type="radio"
                    name="offline-experiments-preview"
                    id={`offline-experiments-preview-${experiment.id}`}
                    aria-label={`${experiment.prompt} ${experiment.model}`}
                    defaultChecked={index === 0}
                    className="OfflineExperimentsPreview__radio"
                    data-attr="offline-experiments-preview-select"
                />
            ))}
            <LemonCard hoverEffect={false} className="p-3">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                    <span className="text-xs font-semibold">Compare experiments</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <LemonTable
                    className="OfflineExperimentsPreview__table"
                    size="small"
                    columns={columns}
                    dataSource={EXPERIMENTS}
                    rowKey="id"
                    onRow={(experiment) => ({ className: `OfflineExperimentsPreview__row--${experiment.id}` })}
                />
                <p className="text-xxs text-muted mt-3 mb-0">
                    Average scores across 50 shared test cases. Select an experiment to inspect a result.
                </p>
            </LemonCard>
            <LemonCard hoverEffect={false} className="p-3">
                <div className="OfflineExperimentsPreview__swap mb-3">
                    {EXPERIMENTS.map((experiment) => (
                        <div
                            key={experiment.id}
                            className={`OfflineExperimentsPreview__when-${experiment.id} flex flex-wrap items-center gap-2`}
                        >
                            <span className="text-xs font-semibold">{experiment.prompt}</span>
                            <LemonTag size="small">{experiment.model}</LemonTag>
                            <span className="text-xxs text-muted">Example result</span>
                        </div>
                    ))}
                </div>
                <div className="text-xxs text-muted mb-1">Input</div>
                <p className="text-xs mb-3">How do I export my data?</p>
                <div className="text-xxs text-muted mb-1">Output</div>
                <div className="OfflineExperimentsPreview__swap">
                    {EXPERIMENTS.map((experiment) => (
                        <div
                            key={experiment.id}
                            className={`OfflineExperimentsPreview__when-${experiment.id}`}
                            role="region"
                            aria-label={`${experiment.prompt} ${experiment.model} result`}
                        >
                            <p className="text-xs mb-3">{experiment.output}</p>
                            <div className="flex flex-wrap gap-2 mb-3">
                                <LemonTag size="small" type={experiment.resultAccuracy >= 0.8 ? 'success' : 'danger'}>
                                    Accuracy: {experiment.resultAccuracy}
                                </LemonTag>
                                <LemonTag
                                    size="small"
                                    type={experiment.resultHelpfulness >= 0.8 ? 'success' : 'danger'}
                                >
                                    Helpfulness: {experiment.resultHelpfulness}
                                </LemonTag>
                            </div>
                            <p className="text-xxs text-muted mb-0">{experiment.reasoning}</p>
                        </div>
                    ))}
                </div>
            </LemonCard>
        </div>
    )
}

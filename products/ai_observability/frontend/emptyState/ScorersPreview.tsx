import './ScorersPreview.scss'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTable, type LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

const SCORERS = [
    { name: 'Answer quality', kind: 'Numeric', format: '0 to 1' },
    { name: 'Groundedness', kind: 'Boolean', format: 'Yes / No' },
    { name: 'Outcome', kind: 'Categorical', format: 'Resolved / Needs help' },
]

const WORKFLOWS = [
    {
        id: 'offline',
        label: 'Offline evaluation',
        title: 'Example: revised prompt · Claude',
        description: 'Record scores from automated checks alongside your experiment results.',
        quality: 0.92,
        grounded: true,
        outcome: 'Resolved',
        reasoning: 'The response answers the question and cites the supplied documentation.',
    },
    {
        id: 'review',
        label: 'Manual review',
        title: 'Example: support agent trace',
        description: 'Inspect a production trace, apply the same scorers, and add your reasoning.',
        quality: 0.6,
        grounded: false,
        outcome: 'Needs help',
        reasoning: 'The answer is clear, but the policy it cites is not in the documentation.',
    },
]

const columns: LemonTableColumns<(typeof SCORERS)[number]> = [
    { title: 'Scorer', dataIndex: 'name', render: (name) => <span className="font-semibold">{name}</span> },
    { title: 'Type', dataIndex: 'kind', render: (kind) => <LemonTag size="small">{kind}</LemonTag> },
    { title: 'Values', dataIndex: 'format' },
]

export function ScorersPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ScorersPreview', isStatic && 'ScorersPreview--static')}>
            {WORKFLOWS.map((workflow, index) => (
                <input
                    key={workflow.id}
                    type="radio"
                    name="scorers-preview-workflow"
                    id={`scorers-preview-${workflow.id}`}
                    defaultChecked={index === 0}
                    className="ScorersPreview__radio"
                    data-attr="scorers-preview-workflow"
                />
            ))}
            <LemonCard hoverEffect={false} className="p-3">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                    <span className="text-xs font-semibold">Reusable scorers</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <LemonTable
                    className="ScorersPreview__table"
                    size="small"
                    columns={columns}
                    dataSource={SCORERS}
                    rowKey="name"
                />
                <p className="text-xxs text-muted mt-3 mb-0">Define each score once. Use it in both workflows.</p>
            </LemonCard>
            <LemonCard hoverEffect={false} className="p-3">
                <div className="ScorersPreview__tabs mb-3">
                    {WORKFLOWS.map((workflow) => (
                        <label
                            key={workflow.id}
                            htmlFor={`scorers-preview-${workflow.id}`}
                            className={`ScorersPreview__tab ScorersPreview__tab--${workflow.id}`}
                        >
                            {workflow.label}
                        </label>
                    ))}
                </div>
                <div className="ScorersPreview__swap">
                    {WORKFLOWS.map((workflow) => (
                        <div
                            key={workflow.id}
                            className={`ScorersPreview__when-${workflow.id}`}
                            role="region"
                            aria-label={`${workflow.label} example`}
                        >
                            <div className="text-xs font-semibold mb-1">{workflow.title}</div>
                            <p className="text-xxs text-muted mb-3">{workflow.description}</p>
                            <dl className="ScorersPreview__scores">
                                <div>
                                    <dt>Answer quality</dt>
                                    <dd>
                                        <LemonTag size="small" type={workflow.quality >= 0.8 ? 'success' : 'danger'}>
                                            {workflow.quality}
                                        </LemonTag>
                                    </dd>
                                </div>
                                <div>
                                    <dt>Groundedness</dt>
                                    <dd>
                                        <LemonTag size="small" type={workflow.grounded ? 'success' : 'danger'}>
                                            {workflow.grounded ? 'Yes' : 'No'}
                                        </LemonTag>
                                    </dd>
                                </div>
                                <div>
                                    <dt>Outcome</dt>
                                    <dd>
                                        <LemonTag size="small">{workflow.outcome}</LemonTag>
                                    </dd>
                                </div>
                            </dl>
                            <div className="text-xxs text-muted mt-3 mb-1">Reasoning</div>
                            <p className="text-xs mb-0">{workflow.reasoning}</p>
                        </div>
                    ))}
                </div>
            </LemonCard>
        </div>
    )
}

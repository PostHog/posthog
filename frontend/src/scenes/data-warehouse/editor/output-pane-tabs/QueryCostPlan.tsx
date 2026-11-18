import clsx from 'clsx'

import { LemonTable } from '@posthog/lemon-ui'

import { CostPlanStep, CostPlanStepKind } from '~/queries/schema/schema-general'

interface QueryCostPlanProps {
    steps: CostPlanStep[]
}

/** The scan estimate and the index verdicts as one plan, read top to bottom the way the query runs. */
export function QueryCostPlan({ steps }: QueryCostPlanProps): JSX.Element {
    return (
        <>
            <p className="text-xs px-2 pt-1 mb-1">
                What the query reads, in order. Expand a line for the reason and, where there is one, the fix.
            </p>
            <LemonTable<CostPlanStep>
                size="small"
                showHeader={false}
                dataSource={steps}
                rowKey={(_, index) => String(index)}
                expandable={{
                    rowExpandable: (step) => !!step.detail || !!step.fix,
                    expandedRowRender: (step) => (
                        <div className="flex flex-col gap-1 px-2 py-1 text-xs">
                            {step.detail && <p className="mb-0">{step.detail}</p>}
                            {step.fix && <p className="mb-0 font-semibold">{step.fix}</p>}
                        </div>
                    ),
                }}
                columns={[
                    {
                        key: 'step',
                        render: (_, step) => (
                            <span
                                className={clsx(
                                    'text-xs',
                                    step.kind === CostPlanStepKind.Filter && 'pl-4 text-secondary',
                                    step.kind === CostPlanStepKind.Join && 'italic'
                                )}
                            >
                                {step.message}
                            </span>
                        ),
                    },
                ]}
            />
        </>
    )
}

import * as scientistPng from '@posthog/brand/hoggies/png/scientist'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { CHECK_STATUS_TAG_TYPES } from '../checksConstants'

const HedgehogScientist = pngHoggie(scientistPng)

const SETUP_STEPS = [
    'Pick a table, view, or metric.',
    'Choose what to assert: not null, unique, accepted values, relationships, row count, freshness, or your own SQL.',
    'See failing checks here and on the page of the model they test.',
]

const EXAMPLE_CHECKS = [
    { name: 'order_id is never null', status: 'failed', detail: '12 failing rows' },
    { name: 'orders arrive daily', status: 'passed', detail: 'Ran 2 hours ago' },
]

export function DataQualityEmptyState({ onAddCheck }: { onAddCheck: () => void }): JSX.Element {
    return (
        <div
            data-attr="data-quality-overview-empty-state"
            className="border rounded p-6 flex flex-col @min-[48rem]/main-content:flex-row gap-6 items-start"
        >
            <div className="flex-1 min-w-0 flex flex-col gap-4">
                <div className="flex items-start gap-4">
                    <HedgehogScientist className="w-24 shrink-0" />
                    <div className="min-w-0">
                        <h2 className="mb-1 text-xl leading-tight">No checks yet</h2>
                        <p className="mb-0 text-secondary">
                            A check tests one thing about your data and runs after each sync or materialization. It
                            tells you when the data stops looking right, before someone reads a dashboard built on it.
                        </p>
                    </div>
                </div>
                <ol className="mb-0 list-decimal pl-5 flex flex-col gap-2 text-secondary">
                    {SETUP_STEPS.map((step) => (
                        <li key={step}>{step}</li>
                    ))}
                </ol>
                <div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={onAddCheck}
                        data-attr="data-quality-overview-first-check"
                    >
                        Add your first check
                    </LemonButton>
                </div>
            </div>
            <div className="w-full @min-[48rem]/main-content:w-80 shrink-0 rounded border bg-surface-secondary">
                <div className="flex items-baseline gap-2 px-3 py-2 border-b">
                    <span className="font-semibold truncate">orders</span>
                    <span className="text-xs text-tertiary">Example</span>
                </div>
                <div className="divide-y">
                    {EXAMPLE_CHECKS.map((check) => (
                        <div key={check.name} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                            <span className="flex-1 min-w-0 truncate">{check.name}</span>
                            <LemonTag type={CHECK_STATUS_TAG_TYPES[check.status]}>{check.status}</LemonTag>
                            <span className="text-tertiary">{check.detail}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

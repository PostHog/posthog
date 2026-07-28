/**
 * PROTOTYPE (throwaway branch, do not merge).
 * Row-by-column paths v2 explorations. Mounted on any paths insight via
 * `?paths_v2_proto=a|b|c` (see InsightVizDisplay). Consumes v1 PathsQuery results
 * client-side; the real PathsV2Query backend is a Build-route concern.
 */
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { LemonSelect, LemonSwitch, LemonTag, Spinner } from '@posthog/lemon-ui'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'

import { pathsDataLogic } from '../pathsDataLogic'
import { buildRowColumnModel } from './rowColumnModel'
import { VariantDraftSankey } from './VariantDraftSankey'
import { VariantJourneyGrid } from './VariantJourneyGrid'
import { VariantStepBars } from './VariantStepBars'

const VARIANTS = [
    { key: 'a', name: 'Journey grid' },
    { key: 'b', name: 'Step bars' },
    { key: 'c', name: 'Draft sankey' },
]

function PrototypeSwitcher({ current }: { current: string }): JSX.Element | null {
    const { push } = useActions(router)
    const { location, searchParams, hashParams } = useValues(router)

    const currentIndex = Math.max(
        VARIANTS.findIndex((v) => v.key === current),
        0
    )
    const goTo = (index: number): void => {
        const next = VARIANTS[(index + VARIANTS.length) % VARIANTS.length]
        push(location.pathname, { ...searchParams, paths_v2_proto: next.key }, hashParams)
    }

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            if (event.key === 'ArrowLeft') {
                goTo(currentIndex - 1)
            } else if (event.key === 'ArrowRight') {
                goTo(currentIndex + 1)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    })

    if (process.env.NODE_ENV === 'production') {
        return null
    }

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-3 rounded-full bg-black text-white px-4 py-2 shadow-lg text-sm select-none">
            <button className="cursor-pointer" onClick={() => goTo(currentIndex - 1)}>
                ←
            </button>
            <span className="font-semibold">
                {VARIANTS[currentIndex].key.toUpperCase()} — {VARIANTS[currentIndex].name}
            </span>
            <button className="cursor-pointer" onClick={() => goTo(currentIndex + 1)}>
                →
            </button>
        </div>
    )
}

export function PathsV2RowColumnPrototype(): JSX.Element {
    const { searchParams } = useValues(router)
    const { insightProps } = useValues(insightLogic)
    const { results, pathsFilter, insightDataLoading, theme } = useValues(pathsDataLogic(insightProps))

    const [maxSteps, setMaxSteps] = useState(5)
    const [maxRows, setMaxRows] = useState(3)
    const [showPercentages, setShowPercentages] = useState(true)

    const model = useMemo(() => buildRowColumnModel(results, maxSteps, maxRows), [results, maxSteps, maxRows])

    const variant = typeof searchParams.paths_v2_proto === 'string' ? searchParams.paths_v2_proto : 'a'
    const nodeColor = theme?.['preset-1'] || '#1d4aff'
    const anchor = pathsFilter?.startPoint || pathsFilter?.endPoint

    return (
        <div className="h-full w-full overflow-auto p-2">
            <div className="flex items-center gap-3 flex-wrap mb-3">
                <LemonTag type="warning">Prototype</LemonTag>
                <LemonTag type={anchor ? 'completion' : 'default'}>
                    {anchor
                        ? `Anchored to ${pathsFilter?.startPoint ? 'start' : 'end'}: ${anchor}`
                        : 'Open paths (per-hop sittings)'}
                </LemonTag>
                <div className="flex items-center gap-1 text-xs">
                    <span className="text-secondary">Max steps</span>
                    <LemonSelect
                        size="xsmall"
                        value={maxSteps}
                        onChange={(value) => value && setMaxSteps(value)}
                        options={[3, 4, 5, 6, 7, 8, 10].map((n) => ({ value: n, label: String(n) }))}
                    />
                </div>
                <div className="flex items-center gap-1 text-xs">
                    <span className="text-secondary">Max rows per step</span>
                    <LemonSelect
                        size="xsmall"
                        value={maxRows}
                        onChange={(value) => value && setMaxRows(value)}
                        options={[1, 2, 3, 4, 5, 8, 10].map((n) => ({ value: n, label: String(n) }))}
                    />
                </div>
                <LemonSwitch label="Percentages" checked={showPercentages} onChange={setShowPercentages} size="small" />
            </div>

            {insightDataLoading ? (
                <div className="flex items-center justify-center h-60">
                    <Spinner className="text-2xl" />
                </div>
            ) : model.columns.length === 0 ? (
                <InsightEmptyState />
            ) : (
                <>
                    {variant === 'b' ? (
                        <VariantStepBars model={model} showPercentages={showPercentages} />
                    ) : variant === 'c' ? (
                        <VariantDraftSankey model={model} nodeColor={nodeColor} />
                    ) : (
                        <VariantJourneyGrid model={model} showPercentages={showPercentages} nodeColor={nodeColor} />
                    )}
                    <div className="text-xs text-secondary mt-2 max-w-200">
                        Counts are unique users per node and per connection. A user can appear in several rows of the
                        same step, so connections into a node may add up to more than its count.
                        {model.hiddenSteps > 0 && ` ${model.hiddenSteps} more steps in the data are not shown.`}
                    </div>
                </>
            )}

            <PrototypeSwitcher current={variant} />
        </div>
    )
}

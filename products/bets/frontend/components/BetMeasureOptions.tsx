import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Button, RadioGroup, RadioGroupItem, Skeleton } from '@posthog/quill'

import type { BetsMeasureOptionApi } from '../generated/api.schemas'
import { number } from '../lib/format'
import { betFormLogic } from '../logics/betFormLogic'
import { BetSparkline } from './BetSparkline'

const AGENT = 'agent'

function detail(option: BetsMeasureOptionApi): string {
    const kind = option.source === 'new' ? 'New measure' : 'Saved insight'
    const counts = option.wait_days > 0 ? `counts a person after ${option.wait_days} days` : null
    const test = option.test_days ? `${option.test_days}-day test` : null
    return [kind, counts, test].filter(Boolean).join(' · ')
}

export function BetMeasureOptions({ id, onRefine }: { id: string; onRefine?: () => void }): JSX.Element | null {
    const logic = betFormLogic({ id })
    const { measureOptions, measureSearchLoading, measuredGoal, form, describing, fromBelief } = useValues(logic)
    const { selectPrimaryInsight, setDescribing, setPicking } = useActions(logic)
    const [open, setOpen] = useState(false)

    if (!measureSearchLoading && !measuredGoal) {
        return null
    }
    const selected = describing ? AGENT : (form.goal_insight ?? '')
    const chosen = !!selected && !open && !measureSearchLoading
    const plotted = !chosen && measureOptions.some((option) => option.current !== null || option.values.length > 1)
    const rows = chosen ? measureOptions.filter((option) => option.insight === selected) : measureOptions
    const found = measureOptions.length
        ? `${measureOptions.length} ${measureOptions.length === 1 ? 'measure fits' : 'measures fit'}`
        : 'No measure fits yet'
    const heading = measureSearchLoading
        ? fromBelief
            ? 'Reading your belief and your data'
            : 'Looking through your insights and events'
        : fromBelief
          ? `From your belief · ${found.charAt(0).toLowerCase()}${found.slice(1)}`
          : found

    return (
        <div className="Bets__measures">
            {!chosen && (
                <div className="Bets__measuresHead">
                    <span>{heading}</span>
                </div>
            )}
            {measureSearchLoading ? (
                <div className="Bets__measureList" aria-busy>
                    {[0, 1].map((index) => (
                        <div key={index} className="Bets__measureItem">
                            <Skeleton className="size-4 rounded-full" />
                            <span className="flex flex-col gap-1.5">
                                <Skeleton className="h-3.5 w-56" />
                                <Skeleton className="h-3 w-40" />
                            </span>
                        </div>
                    ))}
                </div>
            ) : (
                <RadioGroup
                    className="Bets__measureList"
                    data-plotted={plotted || undefined}
                    value={selected}
                    onValueChange={(value: unknown) => {
                        setOpen(false)
                        if (value === AGENT) {
                            setDescribing(true)
                        } else {
                            selectPrimaryInsight(String(value))
                        }
                    }}
                    aria-label="Measures that fit"
                >
                    {rows.map((option) => (
                        <label
                            key={option.insight}
                            className="Bets__measureItem"
                            data-selected={selected === option.insight || undefined}
                            data-attr="bets-form-measure-option"
                        >
                            <RadioGroupItem value={option.insight} />
                            <span className="Bets__measureText">
                                <span className="Bets__measureName">{option.name}</span>
                                <span className="Bets__measureDetail">{detail(option)}</span>
                            </span>
                            {chosen && (
                                <Button
                                    variant="link-muted"
                                    size="inline"
                                    className="Bets__measureChange"
                                    onClick={(event) => {
                                        event.preventDefault()
                                        setOpen(true)
                                    }}
                                    data-attr="bets-form-measure-change"
                                >
                                    Change
                                </Button>
                            )}
                            {plotted && (
                                <span className="Bets__measureData">
                                    <span className="Bets__measureSpark">
                                        {option.values.length > 1 && (
                                            <BetSparkline
                                                label={option.name}
                                                values={option.values}
                                                labels={option.dates}
                                                limit={null}
                                                tone="neutral"
                                            />
                                        )}
                                    </span>
                                    <span className="Bets__measureValue">
                                        {option.current === null ? '' : number(option.current, option.unit)}
                                    </span>
                                </span>
                            )}
                        </label>
                    ))}
                    {(!chosen || describing) && (
                        <label
                            className="Bets__measureItem"
                            data-quiet={(!!measureOptions.length && !describing) || undefined}
                            data-selected={describing || undefined}
                            data-attr="bets-form-measure-agent"
                        >
                            <RadioGroupItem value={AGENT} />
                            <span className="Bets__measureText">
                                <span className="Bets__measureName">
                                    {measureOptions.length && !chosen
                                        ? 'None of these, build a new measure'
                                        : 'Build a new measure'}
                                </span>
                                <span className="Bets__measureDetail">
                                    An agent creates it and checks the tracking. It takes a few minutes.
                                </span>
                            </span>
                            {chosen && (
                                <Button
                                    variant="link-muted"
                                    size="inline"
                                    className="Bets__measureChange"
                                    onClick={(event) => {
                                        event.preventDefault()
                                        setOpen(true)
                                    }}
                                >
                                    Change
                                </Button>
                            )}
                        </label>
                    )}
                </RadioGroup>
            )}
            {!chosen && !measureSearchLoading && (
                <div className="Bets__measuresFoot">
                    {onRefine && (
                        <>
                            <Button
                                variant="link-muted"
                                size="inline"
                                onClick={onRefine}
                                data-attr="bets-form-measure-refine"
                            >
                                {measureOptions.length
                                    ? 'Not quite right? Describe the change'
                                    : 'Describe the change differently'}
                            </Button>
                            <span aria-hidden>·</span>
                        </>
                    )}
                    <Button
                        variant="link-muted"
                        size="inline"
                        onClick={() => setPicking(true)}
                        data-attr="bets-form-measure-mode"
                    >
                        Use an insight I have
                    </Button>
                </div>
            )}
        </div>
    )
}

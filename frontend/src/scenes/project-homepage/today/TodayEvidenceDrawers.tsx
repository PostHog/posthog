import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconBookmark, IconCheck, IconChevronRight, IconCopy, IconPause, IconPlayFilled, IconX } from '@posthog/icons'

import { MAX_DRAWER_DEPTH, TodayDrawer, todayDrawersLogic } from './todayDrawersLogic'
import { DRILL_OPTIONS, SAMPLE_RECENT_ERRORS, SAMPLE_RECORDINGS } from './todayFixtures'
import { TodayIcon } from './TodayIcon'
import { todayLogic } from './todayLogic'

function RecentErrors(): JSX.Element {
    const { drill } = useActions(todayDrawersLogic)
    return (
        <div className="TodayDrawer__section">
            <div className="TodayDrawer__sectionHead">
                <h3>Recent errors</h3>
                <span>Last 24 hours</span>
            </div>
            <div className="TodayDrawer__list">
                {SAMPLE_RECENT_ERRORS.map((error) => (
                    <button
                        key={error.name}
                        type="button"
                        className="TodayDrawer__listRow"
                        onClick={() => drill(error.name)}
                    >
                        <span className="TodayDrawer__errorMark">!</span>
                        <span className="min-w-0">
                            <strong>{error.name}</strong>
                            <small>{error.detail}</small>
                        </span>
                        <span className="TodayDrawer__listCount">
                            <span>{error.count}</span>
                            <small className="Today__mono">{error.time}</small>
                        </span>
                        <IconChevronRight />
                    </button>
                ))}
            </div>
        </div>
    )
}

function CompletionChart(): JSX.Element {
    return (
        <div className="TodayDrawer__section TodayDrawer__chart">
            <div className="TodayDrawer__sectionHead">
                <h3>Checkout completion</h3>
                <span>Last 7 days</span>
            </div>
            <div className="TodayDrawer__chartSummary">
                <strong>49.2%</strong>
                <span>−12.4 points</span>
            </div>
            <svg viewBox="0 0 340 142" fill="none" aria-hidden>
                {[30, 70, 110].map((y) => (
                    <line key={y} x1="0" x2="340" y1={y} y2={y} stroke="#edede8" />
                ))}
                <path d="M0 40 L60 42 L120 44 L180 58 L240 86 L300 98 L340 104 L340 142 L0 142 Z" fill="#2f80fa1a" />
                <path d="M0 40 L60 42 L120 44 L180 58 L240 86 L300 98 L340 104" stroke="#2f80fa" strokeWidth="3" />
                <path d="M0 44 L340 46" stroke="#b8b8b2" strokeDasharray="4 6" />
                <circle cx="334" cy="103" r="5" fill="#fff" stroke="#2f80fa" strokeWidth="3" />
            </svg>
            <div className="TodayDrawer__legend">
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <span style={{ '--legend-color': '#2f80fa' } as React.CSSProperties}>Safari 17</span>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <span style={{ '--legend-color': '#b8b8b2' } as React.CSSProperties}>Other browsers</span>
            </div>
        </div>
    )
}

function RecordingPlayer(): JSX.Element {
    const [selected, setSelected] = useState(0)
    const [playing, setPlaying] = useState(false)
    const recording = SAMPLE_RECORDINGS[selected]
    return (
        <div className="TodayDrawer__section">
            <div className="TodayDrawer__sectionHead">
                <h3>Session recordings</h3>
                <span>{`${selected + 1} of ${SAMPLE_RECORDINGS.length}`}</span>
            </div>
            <div className="TodayPlayer">
                <div className="TodayPlayer__bar">
                    <i />
                    <i />
                    <i />
                    <span>hedgebox.com/checkout</span>
                </div>
                <div className="TodayPlayer__screen">
                    <div className="TodayPlayer__form">
                        <strong>Payment</strong>
                        <i />
                        <i />
                        <span>{recording.step}</span>
                    </div>
                    <span className="TodayPlayer__cursor" data-playing={playing} />
                    <span className="TodayPlayer__note">{recording.note}</span>
                    <button
                        type="button"
                        className="TodayPlayer__play"
                        aria-label={playing ? 'Pause recording' : 'Play recording'}
                        onClick={() => setPlaying(!playing)}
                    >
                        {playing ? <IconPause /> : <IconPlayFilled />}
                    </button>
                </div>
                <div className="TodayPlayer__controls">
                    <i />
                    <span translate="no">{`${playing ? '00:18' : '00:00'} / ${recording.duration}`}</span>
                </div>
            </div>
            <div className="TodayRecordings">
                {SAMPLE_RECORDINGS.map((item, index) => (
                    <button
                        key={item.title}
                        type="button"
                        className="TodayRecording"
                        aria-pressed={index === selected}
                        onClick={() => {
                            setSelected(index)
                            setPlaying(false)
                        }}
                    >
                        <span className="TodayRecording__thumb">
                            <IconPlayFilled />
                        </span>
                        <span>
                            <strong>{item.title}</strong>
                            <small>{item.detail}</small>
                        </span>
                        <span>{item.duration}</span>
                    </button>
                ))}
            </div>
        </div>
    )
}

function DrawerPanel({
    drawer,
    behind,
    offset,
}: {
    drawer: TodayDrawer
    behind: boolean
    offset: number
}): JSX.Element {
    const { copiedDrawerId } = useValues(todayDrawersLogic)
    const { closeTopDrawer, copyDrawer, drill } = useActions(todayDrawersLogic)
    // The rich panels hold sample data, so they stay off for reports built from real reports.
    const { usingSampleReports } = useValues(todayLogic)
    const showSamplePanel = usingSampleReports && drawer.depth === 0
    return (
        <aside
            className="TodayDrawer"
            role="dialog"
            aria-label={drawer.name}
            aria-hidden={behind || undefined}
            data-behind={behind}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--drawer-offset': `${offset}px`, '--tile-color': drawer.color } as React.CSSProperties}
            {...(behind ? { inert: '' } : {})}
        >
            <div className="TodayDrawer__head">
                <div className="TodayDrawer__identity">
                    <span className="TodayTile">
                        <TodayIcon evidence={drawer.kind} />
                    </span>
                    <span>{drawer.name}</span>
                </div>
                <button type="button" className="TodaySecondary" title="Saving evidence is not available yet" disabled>
                    <IconBookmark />
                    <span>Save for later</span>
                </button>
                <button
                    type="button"
                    className="TodayDrawer__iconButton"
                    aria-label={copiedDrawerId === drawer.id ? 'Copied' : 'Copy'}
                    onClick={() => copyDrawer(drawer)}
                >
                    {copiedDrawerId === drawer.id ? <IconCheck /> : <IconCopy />}
                </button>
                <button
                    type="button"
                    className="TodayDrawer__iconButton"
                    aria-label="Close"
                    data-attr="today-drawer-close"
                    onClick={closeTopDrawer}
                >
                    <IconX />
                </button>
            </div>
            <div className="TodayDrawer__body">
                <div className="Today__label">{drawer.kicker}</div>
                <h2>{drawer.value}</h2>
                <p>{drawer.summary}</p>
                <dl className="TodayDrawer__facts">
                    {drawer.facts.map((fact) => (
                        <div key={fact.label}>
                            <dt>{fact.label}</dt>
                            <dd>{fact.value}</dd>
                        </div>
                    ))}
                </dl>
                {showSamplePanel && drawer.kind === 'error' && <RecentErrors />}
                {showSamplePanel && drawer.kind === 'analytics' && <CompletionChart />}
                {showSamplePanel && drawer.kind === 'replay' && <RecordingPlayer />}
                {drawer.depth < MAX_DRAWER_DEPTH ? (
                    <div className="TodayDrill">
                        <div className="TodayDrawer__sectionHead">
                            <h3>Explore this object</h3>
                        </div>
                        {DRILL_OPTIONS[drawer.kind].map((option) => (
                            <button
                                key={option}
                                type="button"
                                className="TodayDrill__row"
                                onClick={() => drill(option)}
                            >
                                <span className="TodayTile">
                                    <TodayIcon evidence={drawer.kind} />
                                </span>
                                <span>{option}</span>
                                <IconChevronRight />
                            </button>
                        ))}
                    </div>
                ) : (
                    <div className="TodayDrill__end">This is as deep as this evidence goes.</div>
                )}
            </div>
        </aside>
    )
}

export function TodayEvidenceDrawers(): JSX.Element | null {
    const { drawers } = useValues(todayDrawersLogic)
    const { closeTopDrawer, closeAllDrawers } = useActions(todayDrawersLogic)

    useEffect(() => {
        if (!drawers.length) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                closeTopDrawer()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [drawers.length, closeTopDrawer])

    if (!drawers.length) {
        return null
    }
    return (
        <div className="TodayDrawerLayer">
            <button
                type="button"
                className="TodayDrawerLayer__backdrop"
                aria-label="Close evidence"
                onClick={closeAllDrawers}
            />
            {drawers.map((drawer, index) => (
                <DrawerPanel
                    key={drawer.id}
                    drawer={drawer}
                    behind={index < drawers.length - 1}
                    offset={(drawers.length - 1 - index) * 18}
                />
            ))}
        </div>
    )
}

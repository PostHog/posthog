import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconArrowRight, IconBell, IconGithub, IconLinear } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { RecordingsUniversalFiltersDisplay } from 'lib/components/Cards/InsightCard/RecordingsUniversalFiltersDisplay'
import { IconSlack } from 'lib/lemon-ui/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import iconZendesk from 'public/services/zendesk.svg'

import { signalSourcesLogic } from './signalSourcesLogic'
import { SignalSourceConfigStatus } from './types'

type SourceProps =
    | {
          icon: React.ReactNode
          title: string
          description: string
          variant: 'coming-soon'
      }
    | {
          icon: React.ReactNode
          title: string
          description: string
          variant: 'available'
          checked: boolean
          loading?: boolean
          /** Whether enabling requires going through a setup flow (shows an arrow icon on the enable button) */
          requiresSetup?: boolean
          onToggle: () => void
          config?: {
              display: React.ReactNode
              buttonLabel: string
              onClick: () => void
          }
          onClearClick?: () => void
          statusSection?: React.ReactNode
      }

function NotifyMeButton({ source }: { source: string }): JSX.Element {
    const [notified, setNotified] = useState(false)

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            disabledReason={notified ? "We'll let you know!" : undefined}
            onClick={() => {
                posthog.capture('signals source interest', { source })
                setNotified(true)
            }}
            icon={<IconBell />}
            className="-my-4" // Prevent the button's height from affecting the row's height
        >
            {notified ? "We'll notify you!" : 'Notify me when available'}
        </LemonButton>
    )
}

function Source(props: SourceProps): JSX.Element {
    const isComingSoon = props.variant === 'coming-soon'

    return (
        <div className="flex gap-3 pb-3 last:pb-0 px-1 items-start">
            <div className="shrink-0 mt-2">{props.icon}</div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-sm">{props.title}</div>
                    {isComingSoon ? (
                        <NotifyMeButton source={props.title} />
                    ) : props.checked ? (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            loading={props.loading}
                            onClick={props.onToggle}
                            className="-my-4"
                        >
                            Disable
                        </LemonButton>
                    ) : (
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            loading={props.loading}
                            icon={props.requiresSetup ? <IconArrowRight /> : undefined}
                            onClick={props.onToggle}
                            className="-my-4"
                        >
                            Enable
                        </LemonButton>
                    )}
                </div>
                <p className="text-xs text-secondary mt-0.25 mb-0">{props.description}</p>
                {!isComingSoon && props.checked && props.config !== undefined && (
                    <>
                        <div className="mt-2 border rounded">
                            <div className="flex items-center justify-between px-2 pt-2">
                                <span className="text-xs font-semibold text-secondary">Filters</span>
                                <div className="flex items-center gap-1">
                                    {props.onClearClick && (
                                        <LemonButton type="tertiary" size="xsmall" onClick={props.onClearClick}>
                                            Clear
                                        </LemonButton>
                                    )}
                                    <LemonButton type="secondary" size="xsmall" onClick={props.config.onClick}>
                                        {props.config.buttonLabel}
                                    </LemonButton>
                                </div>
                            </div>
                            {props.config.display}
                        </div>
                        {props.statusSection}
                    </>
                )}
            </div>
        </div>
    )
}

function isNonEmptyFilters(obj: unknown): boolean {
    return obj != null && typeof obj === 'object' && Object.keys(obj as Record<string, unknown>).length > 0
}

function SessionAnalysisStatusIndicator({ status }: { status: SignalSourceConfigStatus | null }): JSX.Element | null {
    if (status === SignalSourceConfigStatus.RUNNING) {
        return (
            <div className="mt-2 flex items-center gap-2 rounded bg-accent-light text-xs text-accent">
                <Spinner className="size-3.5" />
                <span>Summarizing sessions…</span>
            </div>
        )
    }
    return null
}

export function SourcesList(): JSX.Element {
    const {
        sessionAnalysisConfig,
        githubIssuesConfig,
        linearIssuesConfig,
        zendeskTicketsConfig,
        errorTrackingIsFullyEnabled,
        isSessionAnalysisToggling,
        isGithubIssuesToggling,
        isLinearIssuesToggling,
        isZendeskTicketsToggling,
        isErrorTrackingToggling,
    } = useValues(signalSourcesLogic)
    const {
        toggleSessionAnalysis,
        openSessionAnalysisSetup,
        clearSessionAnalysisFilters,
        initiateDataWarehouseSourceToggle,
        toggleErrorTracking,
    } = useActions(signalSourcesLogic)

    const recordingFilters = sessionAnalysisConfig?.config?.recording_filters
    const hasNonEmptyFilters = isNonEmptyFilters(recordingFilters)

    return (
        <div className="divide-y space-y-3">
            <Source
                icon={
                    <div className="flex *:text-xl group/colorful-product-icons colorful-product-icons-true">
                        {iconForType('session_replay')}
                    </div>
                }
                title="PostHog Session Replay"
                description="Session recordings + event data → Signals"
                variant="available"
                checked={!!sessionAnalysisConfig?.enabled}
                loading={isSessionAnalysisToggling}
                onToggle={() => toggleSessionAnalysis()}
                config={{
                    buttonLabel: recordingFilters ? 'Edit' : 'Configure',
                    onClick: openSessionAnalysisSetup,
                    display: recordingFilters ? (
                        <RecordingsUniversalFiltersDisplay filters={recordingFilters} />
                    ) : (
                        <div className="px-2 pb-2">
                            <span className="text-xs text-secondary">All sessions</span>
                        </div>
                    ),
                }}
                onClearClick={hasNonEmptyFilters ? clearSessionAnalysisFilters : undefined}
                statusSection={<SessionAnalysisStatusIndicator status={sessionAnalysisConfig?.status ?? null} />}
            />

            <Source
                icon={
                    <div className="flex *:text-xl group/colorful-product-icons colorful-product-icons-true">
                        {iconForType('error_tracking')}
                    </div>
                }
                title="PostHog Error Tracking"
                description="New issues, reopenings, and volume spikes → Signals"
                variant="available"
                checked={errorTrackingIsFullyEnabled}
                loading={isErrorTrackingToggling}
                onToggle={() => toggleErrorTracking()}
            />

            <Source
                icon={<img className="size-5" src={iconZendesk} />}
                title="Zendesk"
                description="Incoming support tickets → Signals"
                variant="available"
                checked={!!zendeskTicketsConfig?.enabled}
                loading={isZendeskTicketsToggling}
                requiresSetup
                onToggle={() => initiateDataWarehouseSourceToggle('Zendesk')}
            />

            <Source
                icon={<IconLinear className="size-5" />}
                title="Linear"
                description="New issues and updates → Signals"
                variant="available"
                checked={!!linearIssuesConfig?.enabled}
                loading={isLinearIssuesToggling}
                requiresSetup
                onToggle={() => initiateDataWarehouseSourceToggle('Linear')}
            />

            <Source
                icon={<IconGithub className="size-5" />}
                title="GitHub Issues"
                description="New issues and updates → Signals"
                variant="available"
                checked={!!githubIssuesConfig?.enabled}
                loading={isGithubIssuesToggling}
                requiresSetup
                onToggle={() => initiateDataWarehouseSourceToggle('Github')}
            />

            <Source
                icon={<IconSlack className="size-5 grayscale" />}
                title="Slack"
                description="Messages and threads from channels → Signals"
                variant="coming-soon"
            />
        </div>
    )
}

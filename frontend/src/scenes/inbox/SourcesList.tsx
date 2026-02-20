import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconGithub, IconLinear } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { RecordingsUniversalFiltersDisplay } from 'lib/components/Cards/InsightCard/RecordingsUniversalFiltersDisplay'
import { IconSlack } from 'lib/lemon-ui/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import iconZendesk from 'public/services/zendesk.svg'

import { inboxSceneLogic } from './inboxSceneLogic'

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
          onToggle: () => void
          configSection: React.ReactNode
          configButtonLabel: string
          onConfigClick: () => void
          onClearClick?: () => void
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
                    ) : (
                        <LemonSwitch checked={props.checked} onChange={props.onToggle} />
                    )}
                </div>
                <p className="text-xs text-secondary mt-0.25 mb-0">{props.description}</p>
                {!isComingSoon && props.checked && (
                    <div className="mt-2 border rounded">
                        <div className="flex items-center justify-between px-2 pt-2">
                            <span className="text-xs font-semibold text-secondary">Filters</span>
                            <div className="flex items-center gap-1">
                                {props.onClearClick && (
                                    <LemonButton type="tertiary" size="xsmall" onClick={props.onClearClick}>
                                        Clear
                                    </LemonButton>
                                )}
                                <LemonButton type="secondary" size="xsmall" onClick={props.onConfigClick}>
                                    {props.configButtonLabel}
                                </LemonButton>
                            </div>
                        </div>
                        {props.configSection}
                    </div>
                )}
            </div>
        </div>
    )
}

function isNonEmptyFilters(obj: unknown): boolean {
    return obj != null && typeof obj === 'object' && Object.keys(obj as Record<string, unknown>).length > 0
}

export function SourcesList(): JSX.Element {
    const { sessionAnalysisConfig } = useValues(inboxSceneLogic)
    const { toggleSessionAnalysis, openSessionAnalysisSetup, clearSessionAnalysisFilters } = useActions(inboxSceneLogic)

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
                onToggle={() => toggleSessionAnalysis()}
                configButtonLabel={recordingFilters ? 'Edit' : 'Configure'}
                onConfigClick={openSessionAnalysisSetup}
                onClearClick={hasNonEmptyFilters ? clearSessionAnalysisFilters : undefined}
                configSection={
                    recordingFilters ? (
                        <RecordingsUniversalFiltersDisplay filters={recordingFilters} />
                    ) : (
                        <div className="px-2 pb-2">
                            <span className="text-xs text-secondary">All sessions</span>
                        </div>
                    )
                }
            />

            <Source
                icon={<img className="size-5" src={iconZendesk} />}
                title="Zendesk"
                description="Incoming support tickets → Signals"
                variant="coming-soon"
            />

            <Source
                icon={<IconLinear className="size-5" />}
                title="Linear"
                description="New issues and updates → Signals"
                variant="coming-soon"
            />

            <Source
                icon={<IconGithub className="size-5" />}
                title="GitHub Issues"
                description="New issues and updates → Signals"
                variant="coming-soon"
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

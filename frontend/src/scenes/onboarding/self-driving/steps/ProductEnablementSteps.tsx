import { useActions, useValues } from 'kea'

import { IconBug, IconGraph, IconNotification, IconPullRequest, IconRewindPlay, IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { type EnablementProduct, productEnablementStepLogic } from '../productEnablementStepLogic'

interface BenefitRow {
    icon: JSX.Element
    title: string
    text: string
}

/**
 * Shared layout for the tool steps. Header row: product icon and name on the left, enablement
 * status on the right. Then what the tool is, then what it feeds the agents, then one action zone.
 * The min-height keeps the card from resizing between the three steps; the step definitions pass
 * `title: ''` because the name lives here.
 */
function ToolStepLayout({
    iconType,
    name,
    isOn,
    description,
    benefits,
    note,
    children,
}: {
    iconType: 'product_analytics' | 'session_replay' | 'error_tracking'
    name: string
    isOn: boolean
    description: string
    benefits: BenefitRow[]
    note?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-5 min-h-80 pt-2">
            <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                    <div className="flex *:text-3xl group/colorful-product-icons colorful-product-icons-true">
                        {iconForType(iconType)}
                    </div>
                    <h1 className="text-2xl font-bold m-0">{name}</h1>
                </div>
                <div className={`flex items-center gap-1.5 text-sm shrink-0 ${isOn ? 'text-success' : 'text-muted'}`}>
                    <span className={`size-2 rounded-full ${isOn ? 'bg-success' : 'bg-border-bold'}`} />
                    {isOn ? 'Enabled' : 'Not enabled'}
                </div>
            </div>
            <p className="text-secondary m-0">{description}</p>
            <div className="flex flex-col gap-4">
                {benefits.map(({ icon, title, text }) => (
                    <div key={title} className="flex items-start gap-3">
                        <div
                            className="shrink-0 h-5 flex items-center text-xl"
                            // Rows take the step's own product color (same hue as the header icon),
                            // so each screen is tinted consistently rather than globally accent-orange.
                            style={{ color: `var(--color-product-${iconType.replace(/_/g, '-')}-light)` }}
                        >
                            {icon}
                        </div>
                        <div className="flex flex-col">
                            <span className="text-sm font-semibold">{title}</span>
                            <span className="text-sm text-secondary">{text}</span>
                        </div>
                    </div>
                ))}
            </div>
            {note && <p className="text-xs text-muted m-0">{note}</p>}
            <div className="flex flex-col items-center gap-1 mt-auto pt-2">{children}</div>
        </div>
    )
}

/**
 * Nothing to decide here: events flow as soon as the SDK is in, so this step shows the loop already
 * running before the next steps ask to turn more sources on.
 */
export function AnalyticsStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { registerAnalyticsIntent } = useActions(productEnablementStepLogic)

    useOnMountEffect(() => {
        registerAnalyticsIntent()
    })

    return (
        <ToolStepLayout
            iconType="product_analytics"
            name="Product analytics"
            isOn
            description="How people actually use your product: events, trends, and funnels. This is the baseline context your agents reason from."
            benefits={[
                {
                    icon: <IconGraph />,
                    title: 'Usage data, out of the box',
                    text: 'Events, trends, and funnels start flowing the moment the SDK is installed.',
                },
                {
                    icon: <IconSearch />,
                    title: 'Agents watch your metrics',
                    text: 'Anomalies get investigated automatically.',
                },
                {
                    icon: <IconNotification />,
                    title: 'Findings land in your inbox',
                    text: 'Review what agents found and decide what ships.',
                },
            ]}
        >
            <LemonButton type="primary" status="alt" onClick={onContinue}>
                Continue
            </LemonButton>
        </ToolStepLayout>
    )
}

interface EnableToolStepProps {
    onContinue: () => void
    onSkip: () => void
    product: EnablementProduct
    name: string
    description: string
    benefits: BenefitRow[]
    note?: string
    enableLabel: string
}

/**
 * One tool per step (GDS "one thing per page"): explain what the source feeds, then a single
 * enable-or-skip decision in one action zone.
 */
function EnableToolStep({
    onContinue,
    onSkip,
    product,
    name,
    description,
    benefits,
    note,
    enableLabel,
}: EnableToolStepProps): JSX.Element {
    const { enablingProduct, isSessionReplayEnabled, isErrorTrackingEnabled } = useValues(productEnablementStepLogic)
    const { enableProduct } = useActions(productEnablementStepLogic)

    const isEnabled = product === 'session_replay' ? isSessionReplayEnabled : isErrorTrackingEnabled
    const isEnabling = enablingProduct === product

    return (
        <ToolStepLayout
            iconType={product}
            name={name}
            isOn={isEnabled}
            description={description}
            benefits={benefits}
            note={note}
        >
            {isEnabled ? (
                <LemonButton type="primary" status="alt" onClick={onContinue}>
                    Continue
                </LemonButton>
            ) : (
                <>
                    <LemonButton
                        type="primary"
                        status="alt"
                        loading={isEnabling}
                        disabledReason={
                            enablingProduct !== null && !isEnabling ? 'Another tool is being turned on' : undefined
                        }
                        onClick={() => enableProduct(product, onContinue)}
                    >
                        {enableLabel}
                    </LemonButton>
                    <LemonButton type="tertiary" size="small" onClick={onSkip}>
                        Skip for now
                    </LemonButton>
                </>
            )}
        </ToolStepLayout>
    )
}

export function ReplayStep({ onContinue, onSkip }: { onContinue: () => void; onSkip: () => void }): JSX.Element {
    return (
        <EnableToolStep
            onContinue={onContinue}
            onSkip={onSkip}
            product="session_replay"
            name="Session replay"
            description="Recordings of real sessions, so you and your agents can watch what users actually did."
            benefits={[
                {
                    icon: <IconRewindPlay />,
                    title: 'Watch what users actually did',
                    text: 'Every session is recorded, click by click.',
                },
                {
                    icon: <IconSearch />,
                    title: 'Evidence for investigations',
                    text: 'Agents watch the sessions where an issue happened.',
                },
                {
                    icon: <IconNotification />,
                    title: 'Sessions attached to reports',
                    text: 'Findings link the sessions that show the problem.',
                },
            ]}
            note="Inputs and passwords are masked by default."
            enableLabel="Enable session replay"
        />
    )
}

export function ErrorTrackingStep({ onContinue, onSkip }: { onContinue: () => void; onSkip: () => void }): JSX.Element {
    return (
        <EnableToolStep
            onContinue={onContinue}
            onSkip={onSkip}
            product="error_tracking"
            name="Error tracking"
            description="Exceptions from your product, captured and grouped into issues automatically."
            benefits={[
                {
                    icon: <IconBug />,
                    title: 'Exceptions captured automatically',
                    text: 'No setup beyond the SDK you already installed.',
                },
                {
                    icon: <IconSearch />,
                    title: 'Issues become signals',
                    text: 'New issues, reopenings, and spikes feed your agents.',
                },
                {
                    icon: <IconPullRequest />,
                    title: 'Fixes arrive as pull requests',
                    text: 'Agents investigate and open a fix for your review.',
                },
            ]}
            enableLabel="Enable error tracking"
        />
    )
}

import { useActions, useValues } from 'kea'
import { ComponentType, SVGProps } from 'react'

import { IconDashboard, IconFlag, IconFlask, IconGraph, IconMessage, IconNotebook } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

type IconElement = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>

interface ScopeMeta {
    Icon: IconElement
    verb: string
    color: string
}

// Subtle per-scope accents so the card has variety without turning into a wall of orange.
const SCOPE_META: Record<string, ScopeMeta> = {
    Insight: { Icon: IconGraph, verb: 'created an insight', color: 'text-[var(--color-brand-blue)]' },
    Dashboard: { Icon: IconDashboard, verb: 'shared a dashboard', color: 'text-[var(--color-brand-blue)]' },
    Notebook: { Icon: IconNotebook, verb: 'wrote a notebook', color: 'text-secondary' },
    Experiment: { Icon: IconFlask, verb: 'launched an experiment', color: 'text-[var(--color-brand-yellow)]' },
    FeatureFlag: { Icon: IconFlag, verb: 'shipped a feature flag', color: 'text-[var(--color-brand-blue)]' },
    Survey: { Icon: IconMessage, verb: 'launched a survey', color: 'text-[var(--color-brand-red)]' },
}

const FALLBACK_META: ScopeMeta = { Icon: IconGraph, verb: 'made a change', color: 'text-secondary' }

function scopeMeta(type: string): ScopeMeta {
    const [scope] = type.split('.')
    return SCOPE_META[scope] ?? FALLBACK_META
}

function relativeTime(iso: string): string {
    const now = Date.now()
    const then = new Date(iso).getTime()
    const diffMs = Math.max(0, now - then)
    const minutes = Math.floor(diffMs / 60_000)
    if (minutes < 1) {
        return 'just now'
    }
    if (minutes < 60) {
        return `${minutes}m ago`
    }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) {
        return `${hours}h ago`
    }
    const days = Math.floor(hours / 24)
    if (days < 7) {
        return `${days}d ago`
    }
    const weeks = Math.floor(days / 7)
    return `${weeks}w ago`
}

export function RecentActivityCard(): JSX.Element | null {
    const { recentActivity } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (recentActivity.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <h2 className="text-lg font-semibold mb-4">What your team has been doing</h2>
            <ol className="flex flex-col gap-3 m-0 p-0 list-none">
                {recentActivity.map((item, index) => {
                    const { Icon, verb, color } = scopeMeta(item.type)
                    return (
                        <li key={`${item.type}-${index}`} className="flex items-start gap-3">
                            <div className={`flex-shrink-0 mt-0.5 ${color}`} aria-hidden="true">
                                <Icon className="text-xl" />
                            </div>
                            <div className="flex-1 min-w-0 text-sm leading-snug">
                                <div className="flex items-center gap-1.5 text-muted text-xs">
                                    <ProfilePicture
                                        user={{ first_name: item.actor_name }}
                                        size="xs"
                                        name={item.actor_name}
                                    />
                                    <span className="text-primary font-medium">{item.actor_name}</span>
                                    <span>{verb}</span>
                                    <span aria-hidden="true">·</span>
                                    <span>{relativeTime(item.timestamp)}</span>
                                </div>
                                {item.entity_url ? (
                                    <Link
                                        to={item.entity_url}
                                        subtle
                                        onClick={() => trackCardClick('activity', item.entity_url!)}
                                        className="font-medium break-words"
                                    >
                                        {item.entity_name}
                                    </Link>
                                ) : (
                                    <span className="text-primary font-medium break-words">{item.entity_name}</span>
                                )}
                            </div>
                        </li>
                    )
                })}
            </ol>
        </LemonCard>
    )
}

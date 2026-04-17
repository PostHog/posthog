import { useActions, useValues } from 'kea'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { brandingForScope } from '../productBranding'
import { welcomeDialogLogic } from '../welcomeDialogLogic'

function relativeTime(iso: string): string {
    const now = Date.now()
    const then = new Date(iso).getTime()
    if (Number.isNaN(then)) {
        return 'recently'
    }
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

function looksLikeEmail(value: string): boolean {
    return /\S+@\S+\.\S+/.test(value)
}

export function RecentActivityCard(): JSX.Element | null {
    const { recentActivity } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (recentActivity.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <h2 className="text-lg font-semibold mb-4">What your team has been doing</h2>
            <ol className="flex flex-col gap-3 m-0 p-0 list-none">
                {recentActivity.map((item, index) => {
                    const { branding, verb } = brandingForScope(item.type)
                    const Icon = branding.Icon
                    return (
                        <li key={`${item.type}-${index}`} className="flex items-start gap-3">
                            <div
                                className="flex-shrink-0 w-8 h-8 rounded-md flex items-center justify-center"
                                /* eslint-disable-next-line react/forbid-dom-props */
                                style={{
                                    backgroundColor: `rgb(${branding.rgb} / 0.12)`,
                                    color: `rgb(${branding.rgb})`,
                                }}
                                aria-hidden="true"
                            >
                                <Icon className="text-lg" />
                            </div>
                            <div className="flex-1 min-w-0 text-sm leading-snug">
                                <div className="flex items-center gap-1.5 text-muted text-xs">
                                    <ProfilePicture
                                        user={
                                            looksLikeEmail(item.actor_name)
                                                ? { email: item.actor_name }
                                                : { first_name: item.actor_name }
                                        }
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

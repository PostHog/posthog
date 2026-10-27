import { useState } from 'react'

import { IconArrowRight, IconLightBulb, IconPullRequest, IconWarning } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { urls } from 'scenes/urls'

import type { BetsNextActionApi } from '../generated/api.schemas'
import { IDEA_ICON_COLOR } from '../lib/ideas'

export function BetsNextAction({ item }: { item: BetsNextActionApi }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const needsAttention = item.label === 'Needs attention' || item.label === 'Budget'
    const choose = item.id.endsWith(':choose')
    const betUrl = `${urls.bet(item.bet_id)}${item.work_id ? `?work=${item.work_id}` : choose ? '?section=ideas' : ''}`
    const betLabel = choose ? 'Choose an idea' : 'Review bet'
    return (
        <TodayRow
            tone={needsAttention ? 'risk' : 'neutral'}
            icon={{
                glyph: needsAttention ? (
                    <IconWarning />
                ) : item.url ? (
                    <IconPullRequest />
                ) : choose ? (
                    <IconLightBulb />
                ) : (
                    <IconArrowRight />
                ),
                color: choose ? IDEA_ICON_COLOR : undefined,
            }}
            title={item.title}
            label={choose ? undefined : item.label}
            facts={choose ? [item.bet_title, item.description.split('. ')[0].replace(/\.$/, '')] : [item.bet_title]}
            dataAttr="bets-next-action"
            actions={
                item.url ? (
                    <Button variant="outline" size="sm" render={<LinkPrimitive to={item.url} target="_blank" />}>
                        Review pull request <IconArrowRight />
                    </Button>
                ) : (
                    <Button
                        variant={choose ? 'primary' : 'outline'}
                        size="sm"
                        render={<LinkPrimitive to={betUrl} />}
                        data-attr={choose ? 'bets-next-action-choose' : undefined}
                    >
                        {betLabel} <IconArrowRight />
                    </Button>
                )
            }
            expansion={{
                expanded,
                onToggle: () => setExpanded(!expanded),
                detail: (
                    <div className="TodayRow__detailBody">
                        {item.description && (
                            <LemonMarkdown
                                className="Bets__workDescription max-w-185 whitespace-pre-line wrap-anywhere"
                                lowKeyHeadings
                                disableImages="all"
                                disableMentions
                            >
                                {item.description}
                            </LemonMarkdown>
                        )}
                        <div className="flex flex-wrap items-center gap-3 mt-3">
                            <Button variant="link-muted" size="sm" render={<LinkPrimitive to={betUrl} />}>
                                {betLabel} <IconArrowRight />
                            </Button>
                        </div>
                    </div>
                ),
            }}
        />
    )
}

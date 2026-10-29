import { useMemo } from 'react'

import { IconDocument, IconGithub, IconPullRequest, IconTelescope } from '@posthog/icons'
import { IconStack, IconStackItem, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { getIconColor } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'
import type { TodayObjectPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

export type BetResourceKind =
    | 'insight'
    | 'experiment'
    | 'feature_flag'
    | 'task'
    | 'report'
    | 'scout'
    | 'pull_request'
    | 'repository'

export function BetResourceLink({
    kind,
    title,
    href,
    detail,
    id,
    disabled = false,
}: {
    kind: BetResourceKind
    title: string
    href: string
    detail?: string
    id?: string
    disabled?: boolean
}): JSX.Element {
    const preview = useMemo<TodayObjectPreview>(
        () => ({
            kind: 'object',
            name: title,
            type: kind,
            ref: id ?? null,
            typeLabel: kind.replaceAll('_', ' '),
            folder: [],
            href,
            lastViewedAt: null,
        }),
        [title, kind, id, href]
    )
    const customIcon =
        kind === 'report' ? (
            <IconDocument />
        ) : kind === 'scout' ? (
            <IconTelescope />
        ) : kind === 'pull_request' ? (
            <IconPullRequest />
        ) : kind === 'repository' ? (
            <IconGithub />
        ) : null
    const color =
        kind === 'pull_request'
            ? getIconColor('code_review')[0]
            : kind === 'scout'
              ? 'var(--color-product-self-driving-light)'
              : undefined
    const link = (
        <LinkPrimitive
            to={href}
            disabled={disabled}
            target={kind === 'pull_request' || kind === 'repository' ? '_blank' : undefined}
            className="Bets__resourceLink"
            title={detail ? `${title} · ${detail}` : title}
            data-attr={`bets-resource-${kind}`}
        >
            {customIcon ? (
                <IconStack className="[--icon-stack-size:24px] shrink-0">
                    <IconStackItem color={color}>{customIcon}</IconStackItem>
                </IconStack>
            ) : (
                <TodayObjectIcon type={kind} className="[--icon-stack-size:24px] shrink-0" />
            )}
            <span
                className={
                    kind === 'pull_request' ? 'min-w-0 flex items-center gap-2' : 'min-w-0 flex flex-col gap-0.5'
                }
            >
                <Text size="xs" render={<span />} className="Bets__resourceLinkTitle truncate">
                    {title}
                </Text>
                {detail && (
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        className="Bets__resourceLinkDetail shrink-0 whitespace-nowrap"
                    >
                        {detail}
                    </Text>
                )}
            </span>
        </LinkPrimitive>
    )
    return id && ['insight', 'experiment', 'feature_flag'].includes(kind) ? (
        <div className="min-w-0 max-w-full">
            <TodayPreviewTrigger payload={preview}>{link}</TodayPreviewTrigger>
        </div>
    ) : (
        link
    )
}

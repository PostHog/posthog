import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { TRIGGER_GROUPS_MIN_SDK_VERSION } from 'scenes/settings/environment/replayTriggersLogic'

export type QuillSdkCompatibilityBannerProps =
    | { kind: 'minimized' }
    | { kind: 'recent-traffic'; action: { children: string; onClick: () => void } }
    | { kind: 'outdated-sdk'; pct: string; outdatedCount: number }
    | { kind: 'compatibility' }

export function QuillSdkCompatibilityBanner(props: QuillSdkCompatibilityBannerProps): JSX.Element {
    if (props.kind === 'minimized') {
        return (
            <Item tone="success" size="sm">
                <ItemContent>
                    <ItemDescription>
                        Your recent web SDK traffic is effectively all on v{TRIGGER_GROUPS_MIN_SDK_VERSION}+, so trigger
                        groups apply to essentially every session. The legacy recording conditions below are kept only
                        as a fallback for older SDKs.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    if (props.kind === 'recent-traffic') {
        return (
            <Item tone="info" size="sm" className="flex-wrap">
                <ItemContent>
                    <ItemDescription>
                        Your recent web SDK traffic is on v{TRIGGER_GROUPS_MIN_SDK_VERSION}+, but you haven't set up
                        trigger groups yet. Recording still uses the legacy conditions below. Newer SDKs fall back to
                        them when no trigger groups exist, so nothing changes until you migrate.
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={props.action.onClick}>
                        {props.action.children}
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    if (props.kind === 'outdated-sdk') {
        return (
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        About <strong>{props.pct}%</strong> of recent web traffic (
                        {humanFriendlyNumber(props.outdatedCount)}{' '}
                        {pluralize(props.outdatedCount, 'event', 'events', false)}) is on a posthog-js before v
                        {TRIGGER_GROUPS_MIN_SDK_VERSION}. Those sessions still record using the legacy recording
                        conditions below. Upgrade to v{TRIGGER_GROUPS_MIN_SDK_VERSION}+ for full trigger-group coverage.
                        Both configurations are sent meanwhile, so nothing is lost.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <Item tone="warning" size="sm">
            <ItemContent>
                <ItemTitle>JavaScript SDK version compatibility</ItemTitle>
                <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-xs">
                    <li>
                        SDK versions &gt;= v{TRIGGER_GROUPS_MIN_SDK_VERSION} use trigger groups if configured, otherwise
                        fall back to the legacy recording conditions
                    </li>
                    <li>
                        Both configurations are sent to ensure backward compatibility with all JavaScript SDK versions
                    </li>
                </ul>
            </ItemContent>
        </Item>
    )
}

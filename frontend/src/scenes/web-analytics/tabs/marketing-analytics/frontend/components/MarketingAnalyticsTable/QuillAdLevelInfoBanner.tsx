import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, Text } from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { NativeSourceHierarchyStatus } from '../../logic/marketingAnalyticsLogic'
import { nativeSourceDisplayLabel } from '../../logic/utils'

export function QuillAdLevelInfoBanner({
    isAdGroup,
    fixableSources,
    platformUnsupportedSources,
    dismissKey,
}: {
    isAdGroup: boolean
    fixableSources: NativeSourceHierarchyStatus[]
    platformUnsupportedSources: NativeSourceHierarchyStatus[]
    dismissKey: string
}): JSX.Element | null {
    // The same logic LemonBanner persists its dismissal in, so a banner dismissed on one path stays dismissed on the other.
    const logic = lemonBannerLogic({ dismissKey })
    const { isDismissed } = useValues(logic)
    const { dismiss } = useActions(logic)

    if (isDismissed) {
        return null
    }

    return (
        <Item tone={fixableSources.length > 0 ? 'warning' : 'info'} size="sm">
            <ItemContent className="gap-2">
                <Text size="xs" render={<div />}>
                    Ad group and ad metrics come directly from your ad platform. Conversion goals aren't shown at this
                    level because events can't be attributed to a specific ad.
                </Text>
                {fixableSources.length > 0 && (
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" render={<div />}>
                            {fixableSources.length === 1
                                ? 'One source needs more schemas synced to appear here:'
                                : 'These sources need more schemas synced to appear here:'}
                        </Text>
                        <Text size="xs" render={<ul className="m-0 list-disc pl-5" />}>
                            {fixableSources.map((source) => {
                                const missing = isAdGroup ? source.missingForAdGroup : source.missingForAd
                                return (
                                    <li key={source.sourceId}>
                                        <Button
                                            variant="link"
                                            size="inline"
                                            render={
                                                <LinkPrimitive
                                                    to={`${urls.dataWarehouseSource(`managed-${source.sourceId}`)}?ph_utm_source=ma`}
                                                />
                                            }
                                        >
                                            {nativeSourceDisplayLabel(source.sourceType)}
                                        </Button>
                                        : enable{' '}
                                        {missing.map((schema, idx) => (
                                            <span key={schema}>
                                                <code>{schema}</code>
                                                {idx < missing.length - 1 ? ', ' : ''}
                                            </span>
                                        ))}
                                    </li>
                                )
                            })}
                        </Text>
                    </div>
                )}
                {platformUnsupportedSources.length > 0 && (
                    <Text size="xs" render={<div />}>
                        {platformUnsupportedSources.map((s) => nativeSourceDisplayLabel(s.sourceType)).join(', ')}{' '}
                        {platformUnsupportedSources.length === 1 ? "doesn't" : "don't"} yet expose{' '}
                        {isAdGroup ? 'ad-group' : 'ad'}-level data through PostHog's data warehouse import — coming in a
                        follow-up.
                    </Text>
                )}
            </ItemContent>
            <ItemActions className="self-start">
                <Button size="icon" aria-label="Dismiss" tooltip="Dismiss" onClick={() => dismiss()}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}

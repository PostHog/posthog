import {
    Badge,
    Button,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getTagProps } from 'scenes/max/components/MaxChangelog'
import { ChangelogEntry } from 'scenes/max/maxChangelogLogic'

import { QuillSettingSwitch } from '../components/QuillSettingSwitch'

const BADGE_VARIANT_BY_TAG_TYPE: Record<ReturnType<typeof getTagProps>['type'], 'info' | 'warning' | 'completed'> = {
    highlight: 'info',
    warning: 'warning',
    completion: 'completed',
}

export function QuillMaxChangelogSettings({
    entries,
    hasEntries,
    enabled,
    onToggle,
}: {
    entries: ChangelogEntry[]
    hasEntries: boolean
    enabled: boolean
    onToggle: (checked: boolean) => void
}): JSX.Element {
    if (!hasEntries) {
        return (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                No changelog entries available. Check back later for updates on new PostHog AI features.
            </Text>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <QuillSettingSwitch
                label="Show 'What's new' button in PostHog AI"
                checked={enabled}
                onCheckedChange={onToggle}
            />
            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Recent updates
                </Heading>
                <ItemGroup>
                    {entries.map((entry: ChangelogEntry, index: number) => {
                        const tagProps = entry.tag ? getTagProps(entry.tag) : null

                        return (
                            <Item key={index} variant="outline" size="sm">
                                {tagProps && (
                                    <ItemMedia className="w-16">
                                        <Badge variant={BADGE_VARIANT_BY_TAG_TYPE[tagProps.type]}>
                                            {tagProps.children}
                                        </Badge>
                                    </ItemMedia>
                                )}
                                <ItemContent>
                                    <ItemTitle>{entry.title}</ItemTitle>
                                    <ItemDescription>{entry.description}</ItemDescription>
                                </ItemContent>
                            </Item>
                        )
                    })}
                </ItemGroup>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    See the{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/changelog?team=PostHog+AI" target="_blank" />}
                    >
                        complete changelog
                    </Button>{' '}
                    for all PostHog AI updates.
                </Text>
            </div>
        </div>
    )
}

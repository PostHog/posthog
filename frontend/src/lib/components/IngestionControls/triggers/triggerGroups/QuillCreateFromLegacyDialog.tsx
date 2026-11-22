import {
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

import { QuillTriggerGroupMatchSummary } from './QuillTriggerGroupMatchSummary'

export function QuillCreateFromLegacyDialog({
    isOpen,
    onClose,
    onConfirm,
    previewGroups,
    isCreating,
}: {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => void
    previewGroups: SessionRecordingTriggerGroup[]
    isCreating: boolean
}): JSX.Element {
    const willCreateMultipleGroups = previewGroups.length > 1

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent className="sm:max-w-160">
                <DialogHeader>
                    <DialogTitle>Create trigger groups from legacy settings</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            This will create {pluralize(previewGroups.length, 'trigger group', 'trigger groups')} based
                            on your current legacy trigger settings. You can edit these groups after creating them.
                        </Text>

                        {willCreateMultipleGroups && (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemTitle>Why 2 groups?</ItemTitle>
                                    <ItemDescription>
                                        Your legacy triggers use "ANY" match type, including sampling. This means
                                        recording starts if <strong>any</strong> trigger matches <strong>OR</strong> the
                                        session was sampled. To have functionally equivalent trigger groups, this
                                        requires 2 groups: one to always start recording when the conditions are met,
                                        and one to record the sampled amount of all sessions.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}

                        <div className="flex flex-col gap-2">
                            {previewGroups.map((group, index) => {
                                const hasConditions =
                                    (group.conditions.urls && group.conditions.urls.length > 0) ||
                                    (group.conditions.events && group.conditions.events.length > 0) ||
                                    !!group.conditions.flag

                                return (
                                    <Card key={index} size="sm">
                                        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
                                            <CardTitle>{group.name}</CardTitle>
                                            <div className="flex flex-col items-end">
                                                <Text
                                                    size="lg"
                                                    weight="semibold"
                                                    render={<span className="leading-none" />}
                                                >
                                                    {(group.sampleRate * 100).toFixed(0)}%
                                                </Text>
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    sample rate
                                                </Text>
                                            </div>
                                        </CardHeader>
                                        <CardContent className="flex flex-col gap-2">
                                            <QuillTriggerGroupMatchSummary
                                                hasConditions={!!hasConditions}
                                                matchType={group.conditions.matchType === 'any' ? 'any' : 'all'}
                                            />
                                            {group.conditions.urls && group.conditions.urls.length > 0 && (
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        User has visited URL matching pattern
                                                    </Text>
                                                    {group.conditions.urls.map((u) => (
                                                        <Badge key={u.url}>{u.url}</Badge>
                                                    ))}
                                                </div>
                                            )}
                                            {group.conditions.events && group.conditions.events.length > 0 && (
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        Event
                                                    </Text>
                                                    {group.conditions.events.map((event) => {
                                                        const name = typeof event === 'string' ? event : event.name
                                                        return <Badge key={name}>{name}</Badge>
                                                    })}
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        occurred
                                                    </Text>
                                                </div>
                                            )}
                                            {group.conditions.flag && (
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        Feature flag
                                                    </Text>
                                                    <Badge>
                                                        {typeof group.conditions.flag === 'string'
                                                            ? group.conditions.flag
                                                            : group.conditions.flag.key}
                                                    </Badge>
                                                    <Text size="xs" variant="muted" render={<span />}>
                                                        is enabled
                                                    </Text>
                                                </div>
                                            )}
                                            {group.minDurationMs !== undefined && group.minDurationMs > 0 && (
                                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                    Minimum duration: <b>{group.minDurationMs / 1000}</b> seconds
                                                </Text>
                                            )}
                                        </CardContent>
                                    </Card>
                                )
                            })}
                        </div>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <DialogClose render={<Button variant="outline" disabled={isCreating} />}>Cancel</DialogClose>
                    <Button
                        variant="primary"
                        onClick={onConfirm}
                        loading={isCreating}
                        data-attr="trigger-group-create-from-legacy-confirm"
                    >
                        Create {pluralize(previewGroups.length, 'group')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

import { useValues } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { NOTIFICATION_CONCEPTS } from '../shared/notificationSettingDescriptors'
import { notificationGovernanceLogic } from './notificationGovernanceLogic'
import { QuillNotificationConceptRow } from './QuillNotificationConceptRow'

export function QuillMemberNotifications({
    onDiscard,
    onSave,
    onRetry,
}: {
    onDiscard: () => void
    onSave: () => void
    onRetry: () => void
}): JSX.Element {
    const { members, pendingChangeCount, affectedMemberCount, savingChanges, loadFailed } =
        useValues(notificationGovernanceLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    if (loadFailed) {
        return (
            <Item tone="destructive" size="sm" data-attr="notification-governance-load-failed">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load your members. Try again, and if it keeps happening contact support.
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={onRetry}>
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    if (members === null) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
            </div>
        )
    }

    if (members.length === 0) {
        return (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                This organization has no members yet.
            </Text>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        An override you set here changes only the emails this organization sends. The member's other
                        organizations still use the member's own choice, which they can't change while your override is
                        in place.
                    </ItemDescription>
                </ItemContent>
            </Item>

            {NOTIFICATION_CONCEPTS.filter(
                (concept) => !concept.requiredFeature || hasAvailableFeature(concept.requiredFeature)
            ).map((concept) => (
                <QuillNotificationConceptRow key={concept.setting} concept={concept} />
            ))}

            {pendingChangeCount > 0 && (
                <Item variant="outline" size="sm" className="sticky bottom-0 z-10 flex-wrap bg-background">
                    <ItemContent>
                        <Text size="xs" render={<span />} className="m-0" translate="no">
                            {`${pluralize(pendingChangeCount, 'change')} pending for ${pluralize(
                                affectedMemberCount,
                                'member'
                            )}`}
                        </Text>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            onClick={onDiscard}
                            disabledReason={savingChanges ? 'Saving' : undefined}
                            data-attr="notification-governance-discard"
                        >
                            Discard
                        </Button>
                        <Button
                            variant="primary"
                            onClick={onSave}
                            loading={savingChanges}
                            disabledReason={savingChanges ? 'Saving' : undefined}
                            data-attr="notification-governance-save"
                        >
                            Save
                        </Button>
                    </ItemActions>
                </Item>
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { membersLogic } from '~/models/membersLogic'

import { memberOffboardingLogic } from './memberOffboardingLogic'
import { QuillMemberOffboardingResourceSection } from './QuillMemberOffboardingResourceSection'
import { QuillMemberOffboardingTransferModal } from './QuillMemberOffboardingTransferModal'

export function QuillMemberOffboardingModal({
    title,
    isSelf,
    disabledReason,
    hasResources,
}: {
    title: string
    isSelf: boolean
    disabledReason: string | undefined
    hasResources: boolean
}): JSX.Element {
    const { member, resourcesLoading, loadError, removedLoading, publicResources, subscriptions } =
        useValues(memberOffboardingLogic)
    const { close, loadResources, remove } = useActions(memberOffboardingLogic)
    const { scopedApiKeys, scopedApiKeysLoading } = useValues(membersLogic)

    return (
        <Dialog
            open={!!member}
            onOpenChange={(open) => {
                if (!open && !disabledReason) {
                    close()
                }
            }}
        >
            <DialogContent size={hasResources ? 'wide' : undefined} showCloseButton={!disabledReason}>
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Text size="xs" render={<p className="m-0" />}>
                            {isSelf
                                ? 'Are you sure you want to leave this organization? This cannot be undone. If you leave, you will no longer have access to this organization.'
                                : 'The user will no longer have access to this organization.'}
                        </Text>
                        {resourcesLoading ? (
                            <Skeleton className="h-12" />
                        ) : loadError ? (
                            <Item tone="warning" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        Couldn't load shared resources and subscriptions. You can still remove the
                                        member. Their public links and subscriptions will stay unchanged.
                                    </ItemDescription>
                                </ItemContent>
                                <ItemActions>
                                    <Button variant="outline" onClick={loadResources}>
                                        Retry
                                    </Button>
                                </ItemActions>
                            </Item>
                        ) : hasResources ? (
                            <div className="flex flex-col gap-6" key={member?.user.uuid}>
                                {publicResources.length > 0 && (
                                    <QuillMemberOffboardingResourceSection
                                        resources={publicResources}
                                        kind="public"
                                        isSelf={isSelf}
                                        disabledReason={disabledReason}
                                    />
                                )}
                                {subscriptions.length > 0 && (
                                    <QuillMemberOffboardingResourceSection
                                        resources={subscriptions}
                                        kind="subscriptions"
                                        isSelf={isSelf}
                                        disabledReason={disabledReason}
                                    />
                                )}
                            </div>
                        ) : null}
                        <QuillMemberOffboardingTransferModal />
                        {!scopedApiKeysLoading && !!scopedApiKeys?.keys.length && (
                            <div className="flex flex-col gap-2">
                                <Item tone="warning" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            The following personal API keys will lose access to this organization and
                                            will stop working immediately. Check any services that depend on them before
                                            continuing.
                                        </ItemDescription>
                                    </ItemContent>
                                </Item>
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Name</TableHead>
                                            <TableHead>Last used</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {scopedApiKeys.keys.map((key, index) => (
                                            <TableRow key={index}>
                                                <TableCell>{key.name}</TableCell>
                                                <TableCell>
                                                    {key.last_used_at ? <TZLabel time={key.last_used_at} /> : 'Never'}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close} disabledReason={disabledReason}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive"
                        loading={removedLoading}
                        disabledReason={
                            disabledReason ||
                            (resourcesLoading ? 'Checking shared resources and subscriptions…' : undefined)
                        }
                        onClick={remove}
                        data-attr="confirm-org-member-offboarding"
                    >
                        {isSelf ? 'Leave' : 'Remove'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

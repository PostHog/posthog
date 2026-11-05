import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { addToCollectionItemKey, addToCollectionLogic } from './addToCollectionLogic'

/** Warns that adding items here takes them out of the collections they are in now, since nothing is copied. */
export function AddToCollectionMoveWarning(): JSX.Element {
    const { confirmOpen, leavingOtherCollections, selectedCount } = useValues(addToCollectionLogic)
    const { setConfirmOpen, addSelected } = useActions(addToCollectionLogic)
    const count = leavingOtherCollections.length

    return (
        <AlertDialog open={confirmOpen} onOpenChange={(open: boolean) => !open && setConfirmOpen(false)}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>{`Take ${pluralize(count, 'item')} out of ${count === 1 ? 'its collection' : 'their collections'}?`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        {count === 1
                            ? `1 of ${pluralize(selectedCount, 'item')} is in another collection. Adding it here takes it out of that one. It isn’t copied.`
                            : `${count} of ${pluralize(selectedCount, 'item')} are in other collections. Adding them here takes them out of those. They aren’t copied.`}
                    </AlertDialogDescription>
                    <ul className="m-0 flex max-h-40 list-none flex-col gap-1 overflow-y-auto p-0">
                        {leavingOtherCollections.map((item) => (
                            <li key={addToCollectionItemKey(item)} className="flex min-w-0 items-center gap-2">
                                <Text size="xs" className="min-w-0 truncate">
                                    {item.name}
                                </Text>
                                <Text size="xs" variant="muted" className="shrink-0">
                                    {`from ${item.spaceName}`}
                                </Text>
                            </li>
                        ))}
                    </ul>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => setConfirmOpen(false)}
                        data-attr="analytics-add-items-move-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => addSelected()}
                        data-attr="analytics-add-items-move-confirm"
                    >
                        Confirm
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

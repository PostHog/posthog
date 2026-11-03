import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'

/** Picks the space an item is shared into, or moved to, on the quill Analytics pages. */
export function ShareToSpaceDialog(): JSX.Element {
    const { target, spaces, spacesLoading, sharing, currentSpace, entryLoading } = useValues(analyticsShareLogic)
    const { closeShareToSpace, shareToSpace } = useActions(analyticsShareLogic)
    const moving = !!currentSpace
    const loading = (spacesLoading && !spaces.length) || entryLoading

    return (
        <Dialog open={!!target} onOpenChange={(open: boolean) => !open && closeShareToSpace()}>
            <DialogContent className="max-h-[32rem]" data-attr="analytics-share-dialog">
                <DialogHeader>
                    <DialogTitle>{moving ? 'Move to a collection' : 'Add to a collection'}</DialogTitle>
                    <DialogDescription>
                        {target
                            ? moving
                                ? `"${target.name}" is in ${currentSpace}. Pick where it goes next.`
                                : `Pick the collection "${target.name}" goes in.`
                            : ''}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {loading ? (
                        <div className="flex flex-col gap-2" aria-busy>
                            <Skeleton className="h-10" />
                            <Skeleton className="h-10" />
                        </div>
                    ) : !spaces.length ? (
                        <div className="flex flex-col items-start gap-2">
                            <Text size="sm" variant="muted">
                                No collections yet. Create one first, then add to it.
                            </Text>
                            <Button
                                variant="outline"
                                size="sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.analyticsSpaces()} />}
                                onClick={() => closeShareToSpace()}
                            >
                                Open collections
                            </Button>
                        </div>
                    ) : (
                        <ItemGroup className="flex flex-col gap-1">
                            {spaces.map((space) => {
                                const isCurrent = space.name === currentSpace
                                return (
                                    <Item
                                        key={space.path}
                                        variant="outline"
                                        size="sm"
                                        render={
                                            <button
                                                type="button"
                                                disabled={isCurrent || sharing}
                                                onClick={() => shareToSpace(space)}
                                                data-attr="analytics-share-to-space"
                                            />
                                        }
                                        className="cursor-pointer text-start text-foreground hover:bg-fill-button-tertiary-hover disabled:cursor-default disabled:opacity-60"
                                    >
                                        <ItemMedia aria-hidden>
                                            <AnalyticsSpaceGlyph name={space.name} size="md" />
                                        </ItemMedia>
                                        <ItemContent className="min-w-0">
                                            <ItemTitle>{space.name}</ItemTitle>
                                            <ItemDescription>
                                                {isCurrent
                                                    ? 'Current collection'
                                                    : space.total === 0
                                                      ? 'Empty'
                                                      : `${space.total} ${space.total === 1 ? 'item' : 'items'}`}
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                )
                            })}
                            {moving && (
                                <Item
                                    variant="outline"
                                    size="sm"
                                    render={
                                        <button
                                            type="button"
                                            disabled={sharing}
                                            onClick={() => shareToSpace(null)}
                                            data-attr="analytics-share-make-personal"
                                        />
                                    }
                                    className="cursor-pointer text-start text-foreground hover:bg-fill-button-tertiary-hover"
                                >
                                    <ItemContent className="min-w-0">
                                        <ItemTitle>No collection</ItemTitle>
                                        <ItemDescription>Takes it out of every collection.</ItemDescription>
                                    </ItemContent>
                                </Item>
                            )}
                        </ItemGroup>
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

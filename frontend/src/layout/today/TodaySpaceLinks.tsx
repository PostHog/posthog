import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus, IconStarFilled } from '@posthog/icons'
import { Button, Text, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { newSpaceLogic } from 'products/tasks/frontend/spaces/newSpaceLogic'

import { spaceLabel, sortSpaces, todaySpacesLogic } from './todaySpacesLogic'

export function TodaySpaceLinks(): JSX.Element {
    const { location } = useValues(router)
    const { spaces, spacesLoading, spacesUnavailable } = useValues(todaySpacesLogic)
    const { loadSpaces } = useActions(todaySpacesLogic)
    const { openNewSpace } = useActions(newSpaceLogic)
    return (
        <section
            aria-label="Your spaces"
            className="flex shrink-0 flex-col gap-1 border-b border-border px-2 py-3"
            data-quill
        >
            <div className="flex items-center justify-between">
                <Text size="xs" variant="muted">
                    Your spaces
                </Text>
                <Button size="icon-sm" variant="default" aria-label="Create a space" onClick={openNewSpace}>
                    <IconPlus />
                </Button>
            </div>
            <div className="flex max-h-64 flex-col gap-px overflow-y-auto">
                {spacesLoading && !spaces.length ? (
                    <Skeleton className="h-20 w-full" />
                ) : spacesUnavailable ? (
                    <Button loading={spacesLoading} onClick={() => loadSpaces()}>
                        Try loading spaces again
                    </Button>
                ) : (
                    sortSpaces(spaces)
                        .sort((a, b) => Number(b.starred) - Number(a.starred))
                        .map((space) => (
                            <Button
                                key={space.id}
                                variant="default"
                                className="justify-start aria-[current=page]:bg-fill-selected"
                                aria-current={location.pathname.includes(`/spaces/${space.id}`) ? 'page' : undefined}
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.taskSpace(space.id)} />}
                                data-attr="today-space-link"
                            >
                                <span className="min-w-0 flex-1 truncate text-left">{spaceLabel(space)}</span>
                                {space.starred && <IconStarFilled />}
                            </Button>
                        ))
                )}
                {!spacesLoading && !spacesUnavailable && !spaces.length && (
                    <Button variant="outline" onClick={openNewSpace}>
                        Create your first space
                    </Button>
                )}
            </div>
        </section>
    )
}

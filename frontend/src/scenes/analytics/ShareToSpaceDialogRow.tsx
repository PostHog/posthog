import { IconChevronRight, IconFolder } from '@posthog/icons'
import { Card, Text } from '@posthog/quill'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import { PickerRow } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'

const ROW_CLASS = 'flex w-full items-center gap-2 px-3 py-2 text-left'
const OPENABLE_ROW_CLASS = `${ROW_CLASS} hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`

/** One row of the collection picker: a collection or folder to open, or a muted item already in the open folder. */
export function ShareToSpaceDialogRow({
    row,
    isCurrent,
    onOpen,
}: {
    row: PickerRow
    isCurrent: boolean
    onOpen: (path: string) => void
}): JSX.Element {
    const description = isCurrent ? 'Current location' : row.description
    const label = (
        <span className="flex min-w-0 flex-1 flex-col leading-tight">
            <Text
                size="sm"
                variant={row.kind === 'folder' ? undefined : 'muted'}
                className="m-0 truncate"
                render={<span />}
            >
                {row.name}
            </Text>
            {description && (
                <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                    {description}
                </Text>
            )}
        </span>
    )

    if (row.kind !== 'folder') {
        return (
            <Card size="sm" className="p-0">
                <div className={ROW_CLASS}>
                    <span className="flex size-6 shrink-0 items-center justify-center text-base text-muted-foreground">
                        <AnalyticsTypeIcon type={row.kind} />
                    </span>
                    {label}
                </div>
            </Card>
        )
    }
    return (
        <Card size="sm" className="p-0">
            <button
                type="button"
                className={OPENABLE_ROW_CLASS}
                onClick={() => onOpen(row.path)}
                data-attr="analytics-share-open-folder"
            >
                {splitPath(row.path).length === 1 ? (
                    <AnalyticsSpaceGlyph name={row.name} size="md" />
                ) : (
                    <IconFolder className="size-6 shrink-0 text-muted-foreground" />
                )}
                {label}
                <IconChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            </button>
        </Card>
    )
}

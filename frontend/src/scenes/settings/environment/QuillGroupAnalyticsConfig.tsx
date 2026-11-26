import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import {
    Button,
    Input,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { GroupsAccessStatus, groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { GroupType } from '~/types'

import { groupAnalyticsConfigLogic } from './groupAnalyticsConfigLogic'

export function QuillGroupAnalyticsConfig({
    restrictedReason,
    onDelete,
}: {
    restrictedReason: string | null
    onDelete: (groupType: GroupType) => void
}): JSX.Element {
    const { groupTypes, groupTypesLoading, singularChanges, pluralChanges, hasChanges } =
        useValues(groupAnalyticsConfigLogic)
    const { setSingular, setPlural, reset, save } = useActions(groupAnalyticsConfigLogic)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const rows = Array.from(groupTypes.values())

    return (
        <div className="flex flex-col gap-4">
            {groupsAccessStatus !== GroupsAccessStatus.AlreadyUsing && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Group types will show up here after you send your first event associated with a group. Take
                            a look at{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={
                                    <LinkPrimitive
                                        to="https://posthog.com/docs/product-analytics/group-analytics"
                                        target="_blank"
                                    />
                                }
                            >
                                this guide
                            </Button>{' '}
                            for more information on getting started.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {groupTypesLoading && rows.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : rows.length > 0 ? (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>
                                <Tooltip>
                                    <TooltipTrigger render={<span tabIndex={0} className="cursor-help" />}>
                                        Group type
                                    </TooltipTrigger>
                                    <TooltipContent>As used in code</TooltipContent>
                                </Tooltip>
                            </TableHead>
                            <TableHead>Singular name</TableHead>
                            <TableHead>Plural name</TableHead>
                            <TableHead className="w-12">
                                <span className="sr-only">Actions</span>
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {rows.map((groupType) => (
                            <TableRow key={groupType.group_type_index}>
                                <TableCell>{groupType.group_type}</TableCell>
                                <TableCell>
                                    <Input
                                        size="sm"
                                        aria-label={`Singular name for ${groupType.group_type}`}
                                        value={
                                            singularChanges[groupType.group_type_index] ||
                                            groupType.name_singular ||
                                            groupType.group_type
                                        }
                                        onChange={(event) =>
                                            setSingular(groupType.group_type_index, event.target.value)
                                        }
                                        disabledReason={restrictedReason}
                                    />
                                </TableCell>
                                <TableCell>
                                    <Input
                                        size="sm"
                                        aria-label={`Plural name for ${groupType.group_type}`}
                                        value={
                                            pluralChanges[groupType.group_type_index] ||
                                            groupType.name_plural ||
                                            `${groupType.group_type}(s)`
                                        }
                                        onChange={(event) => setPlural(groupType.group_type_index, event.target.value)}
                                        disabledReason={restrictedReason}
                                    />
                                </TableCell>
                                <TableCell>
                                    <Button
                                        variant="destructive-outline"
                                        size="icon"
                                        aria-label={`Delete ${groupType.group_type}`}
                                        tooltip={`Delete ${groupType.group_type}`}
                                        onClick={() => onDelete(groupType)}
                                        disabledReason={restrictedReason}
                                    >
                                        <IconTrash />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            ) : null}

            <div className="flex flex-wrap gap-2">
                <Button
                    variant="primary"
                    disabledReason={hasChanges ? restrictedReason : 'Make some changes before saving'}
                    onClick={save}
                >
                    Save
                </Button>
                <Button disabledReason={hasChanges ? restrictedReason : 'Revert any changes made'} onClick={reset}>
                    Cancel
                </Button>
            </div>
        </div>
    )
}

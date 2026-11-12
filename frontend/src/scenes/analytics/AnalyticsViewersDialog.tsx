import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
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

import { AnalyticsOwner } from './AnalyticsOwner'
import { analyticsViewersLogic } from './analyticsViewersLogic'

/** Who viewed an item in the last 30 days, how often, and when each person last did. */
export function AnalyticsViewersDialog(): JSX.Element {
    const { target, viewers, viewersLoading, viewersFailed } = useValues(analyticsViewersLogic)
    const { closeViewers, loadViewers } = useActions(analyticsViewersLogic)

    const renderBody = (): JSX.Element => {
        if (viewersFailed) {
            return (
                <Empty className="py-8">
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load the viewers</EmptyTitle>
                        <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            size="sm"
                            loading={viewersLoading}
                            onClick={() => loadViewers()}
                            data-attr="analytics-viewers-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (!viewers) {
            return (
                <div className="flex flex-col gap-2" aria-busy>
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                </div>
            )
        }
        if (!viewers.results.length) {
            return (
                <Empty className="py-8">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconPeople />
                        </EmptyMedia>
                        <EmptyTitle>No views in the last 30 days</EmptyTitle>
                    </EmptyHeader>
                </Empty>
            )
        }
        return (
            <Table size="sm">
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Person</TableHead>
                        <TableHead>Views</TableHead>
                        <TableHead>Last viewed</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {viewers.results.map((viewer) => (
                        <TableRow key={viewer.user.uuid}>
                            <TableCell expand>
                                <AnalyticsOwner
                                    owner={{
                                        ...viewer.user,
                                        first_name: viewer.user.first_name ?? '',
                                        last_name: viewer.user.last_name ?? '',
                                    }}
                                />
                            </TableCell>
                            <TableCell>
                                <Text size="xs">{viewer.view_count.toLocaleString()}</Text>
                            </TableCell>
                            <TableCell>
                                <Text size="xs" variant="muted" render={<span />}>
                                    <TZLabel time={viewer.last_viewed_at} />
                                </Text>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        )
    }

    return (
        <Dialog open={!!target} onOpenChange={(open: boolean) => !open && closeViewers()}>
            <DialogContent className="sm:max-w-120" data-attr="analytics-viewers-dialog">
                <DialogHeader>
                    <DialogTitle>{target ? `Usage of "${target.name}"` : 'Usage'}</DialogTitle>
                    <DialogDescription>
                        Who viewed it in the last 30 days. Each day a person viewed it counts as one view.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="max-h-96">{renderBody()}</DialogBody>
            </DialogContent>
        </Dialog>
    )
}

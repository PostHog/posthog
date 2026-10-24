import { useActions, useValues } from 'kea'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import {
    Dialog,
    DialogBody,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { MATERIALIZATION_ENGINE_LABELS, modelStatusLabel, modelsUsageLogic } from './modelsUsageLogic'

export function ModelsByStatusDialog({
    savedQueryIdToNodeId,
}: {
    savedQueryIdToNodeId: Record<string, string>
}): JSX.Element {
    const { usage, selectedStatusBreakdown } = useValues(modelsUsageLogic)
    const { openModel, setSelectedStatusBreakdown } = useActions(modelsUsageLogic)
    const breakdown = usage?.status_breakdown.find(
        (item) => item.engine === selectedStatusBreakdown?.engine && item.status === selectedStatusBreakdown?.status
    )
    const showError = breakdown?.models.some((model) => model.error) ?? false

    return (
        <Dialog
            open={selectedStatusBreakdown !== null}
            onOpenChange={(open) => !open && setSelectedStatusBreakdown(null)}
        >
            <DialogContent size="wide" className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>
                        {selectedStatusBreakdown
                            ? `${modelStatusLabel(selectedStatusBreakdown.status)} models on ${
                                  MATERIALIZATION_ENGINE_LABELS[selectedStatusBreakdown.engine] ??
                                  selectedStatusBreakdown.engine
                              }`
                            : 'Models by status'}
                    </DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Text size="sm" variant="muted" className="mb-3">
                        These models have this latest run status in the selected date range.
                    </Text>
                    <div className="max-h-[60vh] overflow-auto rounded border border-border">
                        <Table fullWidth>
                            <TableHeader>
                                <TableRow>
                                    <TableHead expand>Model</TableHead>
                                    {showError ? <TableHead expand>Error</TableHead> : null}
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {(breakdown?.models ?? []).map((model) => {
                                    const nodeId = savedQueryIdToNodeId[model.saved_query_id]
                                    return (
                                        <TableRow key={model.saved_query_id}>
                                            <TableCell expand className="min-w-48 max-w-96 break-all">
                                                {model.deleted || !nodeId ? (
                                                    <Text variant="muted" render={<span />}>
                                                        {model.name}
                                                        {model.deleted ? ' (deleted)' : ''}
                                                    </Text>
                                                ) : (
                                                    <LinkPrimitive
                                                        className="font-medium text-link-primary hover:underline"
                                                        to={urls.nodeDetail(nodeId)}
                                                        onClick={() => {
                                                            openModel()
                                                            setSelectedStatusBreakdown(null)
                                                        }}
                                                        data-attr="models-usage-open-status-model"
                                                    >
                                                        {model.name}
                                                    </LinkPrimitive>
                                                )}
                                            </TableCell>
                                            {showError ? (
                                                <TableCell expand className="max-w-[32rem]">
                                                    <Text
                                                        size="xs"
                                                        className="line-clamp-3 break-words font-mono"
                                                        title={model.error ?? undefined}
                                                    >
                                                        {model.error ?? 'N/A'}
                                                    </Text>
                                                </TableCell>
                                            ) : null}
                                        </TableRow>
                                    )
                                })}
                            </TableBody>
                        </Table>
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}

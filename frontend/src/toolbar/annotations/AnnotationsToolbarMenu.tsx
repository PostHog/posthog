import { useActions, useValues } from 'kea'

import { IconCursorClick, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { annotationsLogic } from './annotationsLogic'

export function AnnotationsToolbarMenu(): JSX.Element {
    const { annotations, annotationsLoading, isAnnotating, deletingId } = useValues(annotationsLogic)
    const { startAnnotating, stopAnnotating, deleteAnnotation } = useActions(annotationsLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header className="pt-2">
                <span className="block px-2 pt-3">MCP annotations</span>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="px-2 pb-2 space-y-3">
                    <p className="text-xs text-muted mt-0 mb-4">
                        Point at any element and leave a note. Your AI coding agent can read these over PostHog's MCP
                        and can turn them into changes — then mark them resolved.
                    </p>
                    <p className="text-xs text-muted mt-0 mb-4">
                        Ask your agent for your <strong>project's MCP annotations</strong> to get the list.
                    </p>
                    <LemonButton
                        type="primary"
                        fullWidth
                        center
                        icon={<IconCursorClick />}
                        onClick={() => (isAnnotating ? stopAnnotating() : startAnnotating())}
                    >
                        {isAnnotating ? 'Cancel — click an element…' : 'Annotate an element'}
                    </LemonButton>

                    <div className="space-y-1">
                        <div className="text-xs font-medium text-muted uppercase">Pending</div>
                        {annotationsLoading ? (
                            <div className="flex justify-center py-4">
                                <Spinner />
                            </div>
                        ) : annotations.length > 0 ? (
                            annotations.map((annotation) => (
                                <div
                                    key={annotation.id}
                                    className="rounded border border-border p-2 text-sm bg-bg-light flex items-start gap-2"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="truncate">{annotation.comment}</div>
                                        <div className="text-muted text-xs truncate">{annotation.selector}</div>
                                    </div>
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconTrash />}
                                        tooltip="Delete annotation"
                                        loading={deletingId === annotation.id}
                                        disabledReason={deletingId ? 'Deleting…' : undefined}
                                        onClick={() => deleteAnnotation(annotation.id)}
                                    />
                                </div>
                            ))
                        ) : (
                            <p className="text-muted text-sm text-center py-2">No pending annotations</p>
                        )}
                    </div>
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}

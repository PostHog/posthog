import clsx from 'clsx'

import { IconChevronRight, IconCursorClick, IconDocument } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'

import type { ElementPath, ElementPathNode } from './elementPathsApiTypes'

export interface ElementPathRowProps {
    path: ElementPath
    saveHref: string
    onSaveClick?: () => void
}

function formatShare(share: number): string {
    const percent = share * 100
    return percent > 0 && percent < 1 ? '<1%' : `${Math.round(percent)}%`
}

function nodeTooltip(node: ElementPathNode): string {
    const kind = node.is_anchor ? 'The element you selected' : node.step.type === 'pageview' ? 'Page view' : 'Click'
    const approximate = node.step_is_exact
        ? ''
        : ' Approximate: a journey step saved from it can also match other pages or elements.'
    return `${kind}: ${node.label}.${approximate}`
}

export function ElementPathRow({ path, saveHref, onSaveClick }: ElementPathRowProps): JSX.Element {
    return (
        <li className="flex flex-col gap-1.5 rounded border p-2 min-w-0 bg-surface-primary">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                <span className="text-xs font-semibold whitespace-nowrap" translate="no">
                    {`${pluralize(path.session_count, 'session')} · ${formatShare(path.share_of_anchor_sessions)}`}
                </span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    className="ml-auto shrink-0"
                    to={saveHref}
                    targetBlank
                    onClick={onSaveClick}
                    disabledReason={path.nodes.length < 2 ? 'A journey needs at least 2 steps.' : undefined}
                    data-attr="toolbar-element-journeys-save"
                >
                    Save as journey
                </LemonButton>
            </div>
            <ol className="flex flex-wrap items-center gap-x-0.5 gap-y-1 min-w-0">
                {path.nodes.map((node, index) => (
                    <li key={index} className="flex items-center gap-0.5 min-w-0 max-w-full">
                        {index > 0 && <IconChevronRight className="shrink-0 text-tertiary text-xs" />}
                        <Tooltip title={nodeTooltip(node)}>
                            <span
                                className={clsx(
                                    'inline-flex items-center gap-1 min-w-0 max-w-40 rounded border px-1 py-0.5 text-xs',
                                    node.is_anchor
                                        ? 'border-warning bg-warning-highlight font-semibold'
                                        : 'bg-surface-secondary',
                                    !node.step_is_exact && 'border-dashed'
                                )}
                                data-attr={node.is_anchor ? 'toolbar-element-journeys-anchor' : undefined}
                            >
                                {node.step.type === 'pageview' ? (
                                    <IconDocument className="shrink-0 text-secondary" />
                                ) : (
                                    <IconCursorClick className="shrink-0 text-secondary" />
                                )}
                                <span className="truncate" translate="no">
                                    {node.label}
                                </span>
                            </span>
                        </Tooltip>
                    </li>
                ))}
            </ol>
        </li>
    )
}

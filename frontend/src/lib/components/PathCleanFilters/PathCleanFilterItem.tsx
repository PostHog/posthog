import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { useState } from 'react'

import { IconArrowCircleRight } from '@posthog/icons'
import { LemonSnack, Tooltip } from '@posthog/lemon-ui'
import { Chip, ChipClose, cn } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { isValidRegexp } from 'lib/utils/regexp'

import { PathCleaningFilter } from '~/types'

import { PathRegexModal } from './PathRegexModal'

interface PathCleanFilterItem {
    filter: PathCleaningFilter
    onChange?: (filter: PathCleaningFilter) => void
    onRemove?: () => void
}

export function PathCleanFilterItem({ filter, onChange, onRemove }: PathCleanFilterItem): JSX.Element {
    const [visible, setVisible] = useState(false)
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: String(filter.alias) })
    const quillSurface = useQuillSurface()

    const regex = filter.regex ?? ''
    const isInvalidRegex = !isValidRegexp(regex)
    const invalidRegexReason = isInvalidRegex ? 'NOTE: Invalid Regex, will be skipped' : null
    const title = `${filter.regex} is mapped to ${filter.alias}`
    const onEdit = onChange ? () => setVisible(!visible) : undefined

    return (
        <>
            {visible && onChange && (
                <PathRegexModal
                    filter={filter}
                    isOpen={visible}
                    onClose={() => setVisible(false)}
                    onSave={(filter: PathCleaningFilter) => {
                        onChange(filter)
                        setVisible(false)
                    }}
                />
            )}
            <div
                className="relative"
                ref={setNodeRef}
                {...attributes}
                {...listeners}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ transform: CSS.Translate.toString(transform), transition }}
            >
                {quillSurface ? (
                    <Chip
                        title={title}
                        tooltip={invalidRegexReason}
                        className={cn('max-w-full', isInvalidRegex && 'border-destructive-foreground')}
                    >
                        <button
                            type="button"
                            className="inline-flex min-w-0 items-center gap-1 font-mono text-xs"
                            onClick={onEdit}
                            disabled={!onEdit}
                        >
                            <span className="truncate">{filter.regex ?? '(Empty)'}</span>
                            <IconArrowCircleRight className="shrink-0 text-muted-foreground" />
                            <span className="truncate">{parseAliasToReadable(filter.alias ?? '(Empty)')}</span>
                        </button>
                        {onRemove && <ChipClose onClick={onRemove} aria-label="Remove rule" />}
                    </Chip>
                ) : (
                    <Tooltip title={invalidRegexReason}>
                        <LemonSnack
                            type="pill"
                            onClick={onEdit}
                            onClose={onRemove}
                            title={title}
                            className={clsx({ 'border border-accent': isInvalidRegex })}
                        >
                            <span className="inline-flex items-center">
                                <span className="font-mono text-accent text-xs">{filter.regex ?? '(Empty)'}</span>
                                <IconArrowCircleRight className="mx-2" />
                                <span className="font-mono text-xs">
                                    {parseAliasToReadable(filter.alias ?? '(Empty)')}
                                </span>
                            </span>
                        </LemonSnack>
                    </Tooltip>
                )}
            </div>
        </>
    )
}

// Very opinionated take on what a dynamic path looks like.
// It's either `<dynamic_part>` or `:dynamic_part`
// e.g. /project/<org_id>/notebooks/<notebook_id>/edit
// e.g. /project/:org_id/notebooks/:notebook_id/edit
export const parseAliasToReadable = (alias: string): JSX.Element[] => {
    const parts = alias.split('/')

    return parts.map((part, index) => {
        const includeSlash = index !== parts.length - 1

        if ((part.startsWith('<') && part.endsWith('>')) || part.startsWith(':')) {
            return (
                <span key={index}>
                    <span className="rounded bg-accent-highlight-secondary px-1">{part}</span>
                    <span>{includeSlash ? '/' : ''}</span>
                </span>
            )
        }

        return (
            <span key={index}>
                <span>{part}</span>
                <span>{includeSlash ? '/' : ''}</span>
            </span>
        )
    })
}

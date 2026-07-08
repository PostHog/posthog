import './pagination.css'

import { ChevronLeft, ChevronRight, MoreHorizontal } from 'lucide-react'
import * as React from 'react'

import { Button, type ButtonProps } from './button'
import { cn } from './lib/utils'

/**
 * Presentational pagination control — composable parts (no internal state). The
 * consumer owns page state and renders an item per page; wire `onClick`/`disabled`
 * on the buttons. Use {@link getPaginationRange} to build a first/last + sibling
 * window with ellipses for large page counts.
 */
function Pagination({ className, ...props }: React.ComponentProps<'nav'>): React.ReactElement {
    return (
        <nav
            aria-label="Pagination"
            data-quill
            data-slot="pagination"
            className={cn('quill-pagination', className)}
            {...props}
        />
    )
}

const PaginationContent = React.forwardRef<HTMLUListElement, React.ComponentProps<'ul'>>(function PaginationContent(
    { className, ...props },
    ref
) {
    return (
        <ul
            ref={ref}
            data-slot="pagination-content"
            className={cn('quill-pagination__content', className)}
            {...props}
        />
    )
})

const PaginationItem = React.forwardRef<HTMLLIElement, React.ComponentProps<'li'>>(function PaginationItem(
    { className, ...props },
    ref
) {
    return <li ref={ref} data-slot="pagination-item" className={cn('quill-pagination__item', className)} {...props} />
})

type PaginationButtonProps = ButtonProps & {
    /** Marks the current page — sets `aria-current="page"` and the selected fill. */
    isActive?: boolean
}

// A page button. Reuses the Button's `aria-selected` fill for the active page so
// it matches the rest of the system; real semantics live in `aria-current`.
const PaginationButton = React.forwardRef<HTMLButtonElement, PaginationButtonProps>(function PaginationButton(
    { isActive, size = 'icon-sm', className, ...props },
    ref
) {
    return (
        <Button
            ref={ref}
            data-slot="pagination-button"
            aria-current={isActive ? 'page' : undefined}
            aria-selected={isActive ? true : undefined}
            size={size}
            className={cn('quill-pagination__button', className)}
            {...props}
        />
    )
})

const PaginationPrevious = React.forwardRef<HTMLButtonElement, Omit<PaginationButtonProps, 'isActive'>>(
    function PaginationPrevious({ className, children, ...props }, ref) {
        return (
            <PaginationButton
                ref={ref}
                aria-label="Go to previous page"
                size="sm"
                className={cn('gap-1 px-2', className)}
                {...props}
            >
                <ChevronLeft className="size-3.5" />
                {children ?? <span>Previous</span>}
            </PaginationButton>
        )
    }
)

const PaginationNext = React.forwardRef<HTMLButtonElement, Omit<PaginationButtonProps, 'isActive'>>(
    function PaginationNext({ className, children, ...props }, ref) {
        return (
            <PaginationButton
                ref={ref}
                aria-label="Go to next page"
                size="sm"
                className={cn('gap-1 px-2', className)}
                {...props}
            >
                {children ?? <span>Next</span>}
                <ChevronRight className="size-3.5" />
            </PaginationButton>
        )
    }
)

function PaginationEllipsis({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            aria-hidden
            data-slot="pagination-ellipsis"
            className={cn('quill-pagination__ellipsis', className)}
            {...props}
        >
            <MoreHorizontal className="size-3.5" />
            <span className="sr-only">More pages</span>
        </span>
    )
}

type PaginationRangeItem = number | 'ellipsis'

// Builds the page-number window: first + last page always shown, `siblingCount`
// pages on each side of the current page, and an 'ellipsis' token wherever a gap
// is collapsed. All indices are 0-based (matching TanStack's `pageIndex`); shift
// by +1 for display. Returns the full contiguous range when it would fit anyway.
function getPaginationRange(pageCount: number, pageIndex: number, siblingCount = 1): PaginationRangeItem[] {
    // first, last, current, the two ellipses, and a sibling on each side.
    const slots = siblingCount * 2 + 5
    if (pageCount <= slots) {
        return Array.from({ length: pageCount }, (_, i) => i)
    }

    const leftSibling = Math.max(pageIndex - siblingCount, 0)
    const rightSibling = Math.min(pageIndex + siblingCount, pageCount - 1)
    // Show an ellipsis only when it hides more than one page (otherwise just show the page).
    const showLeftEllipsis = leftSibling > 2
    const showRightEllipsis = rightSibling < pageCount - 3
    const first = 0
    const last = pageCount - 1

    const range: PaginationRangeItem[] = [first]
    if (showLeftEllipsis) {
        range.push('ellipsis')
    } else {
        for (let i = 1; i < leftSibling; i++) {
            range.push(i)
        }
    }
    for (let i = leftSibling; i <= rightSibling; i++) {
        if (i !== first && i !== last) {
            range.push(i)
        }
    }
    if (showRightEllipsis) {
        range.push('ellipsis')
    } else {
        for (let i = rightSibling + 1; i < last; i++) {
            range.push(i)
        }
    }
    range.push(last)
    return range
}

Pagination.displayName = 'Pagination'
PaginationContent.displayName = 'PaginationContent'
PaginationItem.displayName = 'PaginationItem'
PaginationButton.displayName = 'PaginationButton'
PaginationPrevious.displayName = 'PaginationPrevious'
PaginationNext.displayName = 'PaginationNext'

export {
    Pagination,
    PaginationContent,
    PaginationItem,
    PaginationButton,
    PaginationPrevious,
    PaginationNext,
    PaginationEllipsis,
    getPaginationRange,
    type PaginationRangeItem,
}

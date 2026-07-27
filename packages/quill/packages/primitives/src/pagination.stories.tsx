import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import {
    getPaginationRange,
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
} from './pagination'

const meta = {
    title: 'Primitives/Pagination',
    component: Pagination,
    tags: ['autodocs'],
} satisfies Meta<typeof Pagination>

export default meta
type Story = StoryObj<typeof meta>

// Composable parts wired to local state. `getPaginationRange` collapses large
// page counts to first/last + a sibling window with ellipses; `siblingCount`
// widens that window.
function PaginationDemo({
    pageCount,
    initialPage = 0,
    siblingCount,
}: {
    pageCount: number
    initialPage?: number
    siblingCount?: number
}): React.ReactElement {
    const [pageIndex, setPageIndex] = React.useState(initialPage)
    const range = getPaginationRange(pageCount, pageIndex, siblingCount)
    return (
        <Pagination>
            <PaginationContent>
                <PaginationItem>
                    <PaginationPrevious
                        disabled={pageIndex === 0}
                        onClick={() => setPageIndex((i) => Math.max(0, i - 1))}
                    />
                </PaginationItem>
                {range.map((item, i) =>
                    item === 'ellipsis' ? (
                        <PaginationItem key={`ellipsis-${i}`}>
                            <PaginationEllipsis />
                        </PaginationItem>
                    ) : (
                        <PaginationItem key={item}>
                            <PaginationButton isActive={item === pageIndex} onClick={() => setPageIndex(item)}>
                                {item + 1}
                            </PaginationButton>
                        </PaginationItem>
                    )
                )}
                <PaginationItem>
                    <PaginationNext
                        disabled={pageIndex === pageCount - 1}
                        onClick={() => setPageIndex((i) => Math.min(pageCount - 1, i + 1))}
                    />
                </PaginationItem>
            </PaginationContent>
        </Pagination>
    )
}

// A handful of pages — every page fits, no ellipsis. Previous is disabled on the
// first page.
export const Default: Story = {
    render: () => <PaginationDemo pageCount={5} />,
}

// One page: both arrows disabled, a single active button.
export const SinglePage: Story = {
    render: () => <PaginationDemo pageCount={1} />,
}

// The boundary count (siblingCount*2 + 5 = 7) still renders contiguously — one
// more page is where ellipses start.
export const ExactFit: Story = {
    render: () => <PaginationDemo pageCount={7} />,
}

// Current page near the start → only a trailing ellipsis before the last page.
export const RightEllipsis: Story = {
    render: () => <PaginationDemo pageCount={20} initialPage={1} />,
}

// Current page in the middle of a long range → ellipses on both sides.
export const BothEllipses: Story = {
    render: () => <PaginationDemo pageCount={20} initialPage={9} />,
}

// Current page near the end → only a leading ellipsis after the first page.
export const LeftEllipsis: Story = {
    render: () => <PaginationDemo pageCount={20} initialPage={18} />,
}

// `siblingCount={2}` shows two pages either side of the current one before
// collapsing the rest.
export const WideSiblingWindow: Story = {
    render: () => <PaginationDemo pageCount={20} initialPage={9} siblingCount={2} />,
}

// Compact pager — just the arrows and a page indicator, no numbered buttons.
// `sr-only` children keep the arrows icon-only while staying labelled for ATs.
function CompactDemo(): React.ReactElement {
    const pageCount = 12
    const [pageIndex, setPageIndex] = React.useState(0)
    return (
        <Pagination>
            <PaginationContent>
                <PaginationItem>
                    <PaginationPrevious disabled={pageIndex === 0} onClick={() => setPageIndex((i) => i - 1)}>
                        <span className="sr-only">Previous</span>
                    </PaginationPrevious>
                </PaginationItem>
                <PaginationItem>
                    <span className="px-2 text-xs text-muted-foreground tabular-nums">
                        Page {pageIndex + 1} of {pageCount}
                    </span>
                </PaginationItem>
                <PaginationItem>
                    <PaginationNext disabled={pageIndex === pageCount - 1} onClick={() => setPageIndex((i) => i + 1)}>
                        <span className="sr-only">Next</span>
                    </PaginationNext>
                </PaginationItem>
            </PaginationContent>
        </Pagination>
    )
}

export const Compact: Story = {
    render: () => <CompactDemo />,
}

// Custom arrow labels via children on Previous / Next.
function CustomLabelsDemo(): React.ReactElement {
    const pageCount = 8
    const [pageIndex, setPageIndex] = React.useState(0)
    return (
        <Pagination>
            <PaginationContent>
                <PaginationItem>
                    <PaginationPrevious disabled={pageIndex === 0} onClick={() => setPageIndex((i) => i - 1)}>
                        Newer
                    </PaginationPrevious>
                </PaginationItem>
                <PaginationItem>
                    <PaginationNext disabled={pageIndex === pageCount - 1} onClick={() => setPageIndex((i) => i + 1)}>
                        Older
                    </PaginationNext>
                </PaginationItem>
            </PaginationContent>
        </Pagination>
    )
}

export const CustomLabels: Story = {
    render: () => <CustomLabelsDemo />,
}

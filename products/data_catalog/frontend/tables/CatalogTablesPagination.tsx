import {
    Pagination,
    PaginationButton,
    PaginationContent,
    PaginationEllipsis,
    PaginationItem,
    PaginationNext,
    PaginationPrevious,
    getPaginationRange,
} from '@posthog/quill'

export interface CatalogTablesPaginationProps {
    currentPage: number
    pageCount: number
    pageSize: number
    total: number
    onPageChange: (page: number) => void
}

export function CatalogTablesPagination({
    currentPage,
    pageCount,
    pageSize,
    total,
    onPageChange,
}: CatalogTablesPaginationProps): JSX.Element {
    const pageIndex = currentPage - 1
    const start = pageIndex * pageSize + 1
    const end = Math.min(currentPage * pageSize, total)

    return (
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-2">
            <span className="text-xs tabular-nums text-muted-foreground">
                {start}–{end} of {total}
            </span>
            <Pagination className="w-auto">
                <PaginationContent>
                    <PaginationItem>
                        <PaginationPrevious disabled={currentPage === 1} onClick={() => onPageChange(currentPage - 1)}>
                            <span className="sr-only">Previous</span>
                        </PaginationPrevious>
                    </PaginationItem>
                    {getPaginationRange(pageCount, pageIndex).map((item, index) =>
                        item === 'ellipsis' ? (
                            <PaginationItem key={`ellipsis-${index}`}>
                                <PaginationEllipsis />
                            </PaginationItem>
                        ) : (
                            <PaginationItem key={item}>
                                <PaginationButton
                                    isActive={item === pageIndex}
                                    aria-label={`Go to page ${item + 1}`}
                                    onClick={() => onPageChange(item + 1)}
                                >
                                    {item + 1}
                                </PaginationButton>
                            </PaginationItem>
                        )
                    )}
                    <PaginationItem>
                        <PaginationNext
                            disabled={currentPage === pageCount}
                            onClick={() => onPageChange(currentPage + 1)}
                        >
                            <span className="sr-only">Next</span>
                        </PaginationNext>
                    </PaginationItem>
                </PaginationContent>
            </Pagination>
        </div>
    )
}

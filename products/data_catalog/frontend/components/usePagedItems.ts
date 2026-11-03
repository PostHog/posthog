import { useState } from 'react'

export interface PagedItems<T> {
    pageItems: T[]
    currentPage: number
    pageCount: number
    setPage: (page: number) => void
}

export function usePagedItems<T>(items: T[], pageSize: number): PagedItems<T> {
    const [requestedPage, setPage] = useState(1)
    const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
    const currentPage = Math.min(requestedPage, pageCount)
    const start = (currentPage - 1) * pageSize
    return { pageItems: items.slice(start, start + pageSize), currentPage, pageCount, setPage }
}

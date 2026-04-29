import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { BackButton } from './BackButton'
import { LoadingState } from './LoadingState'
import { Stack } from './Stack'

export interface ListDetailViewProps<TItem, TDetail = TItem> {
    onItemClick: ((item: TItem) => Promise<TDetail | null>) | undefined
    backLabel: string
    getItemName: (item: TItem) => string
    renderDetail: (detail: TDetail) => ReactNode
    renderList: (handleClick: (item: TItem) => void) => ReactNode
}

type ViewState<TDetail> = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; detail: TDetail }

export function ListDetailView<TItem, TDetail = TItem>({
    onItemClick,
    backLabel,
    getItemName,
    renderDetail,
    renderList,
}: ListDetailViewProps<TItem, TDetail>): ReactElement {
    const [viewState, setViewState] = useState<ViewState<TDetail>>({ view: 'list' })

    const handleClick = useCallback(
        async (item: TItem) => {
            if (!onItemClick) {
                return
            }

            setViewState({ view: 'loading', name: getItemName(item) })
            const detail = await onItemClick(item).catch((error) => {
                console.error(`Error loading detail:`, error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onItemClick, getItemName]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label={backLabel} />
                    <LoadingState label={viewState.name} />
                </Stack>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <Stack gap="sm">
                    <BackButton onClick={handleBack} label={backLabel} />
                    {renderDetail(viewState.detail)}
                </Stack>
            </div>
        )
    }

    return <>{renderList(handleClick)}</>
}

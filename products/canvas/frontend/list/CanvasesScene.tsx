import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPalette, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { CanvasApi } from '../generated/api.schemas'
import { CANVASES_PAGE_SIZE, canvasesListLogic } from './canvasesListLogic'

export const scene: SceneExport = {
    component: CanvasesScene,
    logic: canvasesListLogic,
}

// The canvases list is part of the Today rail redesign, so it renders only behind its flag.
export function CanvasesScene(): JSX.Element {
    const canvasesEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return canvasesEnabled ? <CanvasesList /> : <NotFound object="page" />
}

function CanvasesList(): JSX.Element {
    const { canvases, canvasesResponse, canvasesResponseLoading, search, ordering, page } = useValues(canvasesListLogic)
    const { loadCanvases, setSearch, setOrdering, setPage, deleteCanvas } = useActions(canvasesListLogic)

    // Loads on mount rather than on the route, because the list only mounts once the flag is on.
    useOnMountEffect(loadCanvases)

    const columns: LemonTableColumns<CanvasApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            width: '100%',
            render: (_, canvas) => (
                <Link data-attr="canvas-title" to={urls.canvasDetail(canvas.id)} className="font-semibold">
                    {canvas.name || 'Untitled canvas'}
                </Link>
            ),
        },
        // The column is typed for the handwritten user type, not the generated one.
        // The API cannot sort by creator, so the column drops its sorter.
        { ...createdByColumn(), sorter: undefined } as unknown as LemonTableColumns<CanvasApi>[number],
        { ...atColumn<CanvasApi>('created_at', 'Created'), sorter: true } as LemonTableColumns<CanvasApi>[number],
        { ...atColumn<CanvasApi>('updated_at', 'Last modified'), sorter: true } as LemonTableColumns<CanvasApi>[number],
        {
            width: 0,
            render: (_, canvas) => (
                <LemonMenu
                    items={[
                        {
                            label: 'Delete',
                            icon: <IconTrash />,
                            status: 'danger',
                            onClick: () => deleteCanvas(canvas),
                            'data-attr': 'canvases-delete',
                        },
                    ]}
                >
                    <LemonButton aria-label="More" icon={<IconEllipsis />} size="small" />
                </LemonMenu>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Canvases"
                resourceType={{ type: 'canvas', forceIcon: <IconPalette /> }}
                actions={
                    <LemonButton size="small" type="primary" to={urls.canvasNew()} data-attr="canvases-new">
                        New canvas
                    </LemonButton>
                }
            />
            <LemonInput
                type="search"
                placeholder="Search for canvases"
                value={search}
                onChange={setSearch}
                className="max-w-80"
                data-attr="canvases-search"
            />
            <LemonTable
                data-attr="canvases-table"
                dataSource={canvases}
                rowKey="id"
                columns={columns}
                loading={canvasesResponseLoading}
                // The API sorts newest first by one of the two dates, so those are the only sorts offered.
                sorting={{ columnKey: ordering === '-created_at' ? 'created_at' : 'updated_at', order: -1 }}
                onSort={(sorting) => setOrdering(sorting?.columnKey === 'created_at' ? '-created_at' : '-updated_at')}
                noSortingCancellation
                useURLForSorting={false}
                pagination={{
                    controlled: true,
                    pageSize: CANVASES_PAGE_SIZE,
                    currentPage: page,
                    entryCount: canvasesResponse?.count ?? 0,
                    onForward: canvasesResponse?.next ? () => setPage(page + 1) : undefined,
                    onBackward: page > 1 ? () => setPage(page - 1) : undefined,
                }}
                emptyState={search ? 'No canvases match that search.' : 'No canvases yet. Create one to get started.'}
                nouns={['canvas', 'canvases']}
            />
        </SceneContent>
    )
}

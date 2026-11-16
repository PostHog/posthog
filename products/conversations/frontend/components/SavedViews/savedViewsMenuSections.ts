import type { SavedTicketView } from '../../types'

export interface SavedViewsMenuItem {
    label: string
    onClick?: () => void
    disabledReason?: string
    'data-attr'?: string
}

export interface SavedViewsMenuSection {
    title?: string
    items: SavedViewsMenuItem[]
}

/** The saved views menu: the favorite views, then the actions to save or browse views. */
export function savedViewsMenuSections({
    favoriteViews,
    viewsLoading,
    editDisabledReason,
    loadView,
    openSaveModal,
    openModal,
}: {
    favoriteViews: SavedTicketView[]
    viewsLoading: boolean
    editDisabledReason: string | undefined
    loadView: (view: SavedTicketView) => void
    openSaveModal: () => void
    openModal: () => void
}): SavedViewsMenuSection[] {
    return [
        {
            title: 'Favorites',
            items: favoriteViews.length
                ? favoriteViews.map((view) => ({
                      label: view.name,
                      onClick: () => loadView(view),
                  }))
                : [
                      {
                          label: viewsLoading ? 'Loading…' : 'No favorite views yet',
                          disabledReason: 'Favorite a view to see it here',
                      },
                  ],
        },
        {
            items: [
                {
                    label: 'Save current view',
                    onClick: openSaveModal,
                    disabledReason: editDisabledReason,
                    'data-attr': 'tickets-save-current-view',
                },
                { label: 'All saved views', onClick: openModal },
            ],
        },
    ]
}

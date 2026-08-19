import { IconBookmark, IconHeartFilled } from '@posthog/icons'

import type { LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { SavedTicketView } from '../../types'

/** Personal favorites sit above the team-shared folder tree. */
export const FAVORITES_NODE_ID = 'favorites'

const FOLDER_ID_PREFIX = 'folder://'

/**
 * Node ids are prefixed by kind because LemonTree keys both expansion and selection by id, and a
 * favorited view appears twice — once under Favorites and once in its folder. Unprefixed ids would
 * make expanding one row toggle the other.
 */
export function folderNodeId(path: string): string {
    return `${FOLDER_ID_PREFIX}${path}`
}

export function viewNodeId(shortId: string): string {
    return `view://${shortId}`
}

export function favoriteNodeId(shortId: string): string {
    return `fav://${shortId}`
}

/** The folder a tree node represents, or null for view rows and the Favorites node. */
export function folderPathFromNodeId(id: string): string | null {
    return id.startsWith(FOLDER_ID_PREFIX) ? id.slice(FOLDER_ID_PREFIX.length) : null
}

/** Every folder any view sits in, plus each of their ancestors, sorted for a folder picker. */
export function ticketViewFolderPaths(views: SavedTicketView[]): string[] {
    const paths = new Set<string>()
    for (const view of views) {
        const segments = splitPath(view.folder)
        for (let depth = 1; depth <= segments.length; depth++) {
            paths.add(joinPath(segments.slice(0, depth)))
        }
    }
    return [...paths].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
}

/** Node ids for `path` and all its ancestors, so revealing a folder expands the whole chain. */
export function ancestorFolderNodeIds(path: string): string[] {
    const segments = splitPath(path)
    return segments.map((_, index) => folderNodeId(joinPath(segments.slice(0, index + 1))))
}

interface FolderBranch {
    /** Carried alongside `path` so adding a child never re-parses the parent's path. */
    segments: string[]
    path: string
    name: string
    folders: Map<string, FolderBranch>
    views: SavedTicketView[]
}

function emptyBranch(segments: string[]): FolderBranch {
    return {
        segments,
        path: joinPath(segments),
        name: segments[segments.length - 1] ?? '',
        folders: new Map(),
        views: [],
    }
}

function byName(a: { name: string }, b: { name: string }): number {
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
}

function viewNode(view: SavedTicketView, id: string): TreeDataItem {
    return {
        id,
        name: view.name,
        icon: <IconBookmark />,
        // Favoriting is per-user, so the heart is state here rather than a control; the row menus
        // carry the toggle. LemonTree rows are themselves buttons, so a nested button is invalid.
        sideIcon: view.is_favorited ? <IconHeartFilled className="text-danger" /> : undefined,
        record: { type: 'view', view },
    }
}

function branchToNode(branch: FolderBranch): TreeDataItem {
    const folders = [...branch.folders.values()].sort(byName).map(branchToNode)
    const views = [...branch.views].sort(byName).map((view) => viewNode(view, viewNodeId(view.short_id)))
    return {
        id: folderNodeId(branch.path),
        name: branch.name,
        record: { type: 'folder', path: branch.path },
        children: [...folders, ...views],
    }
}

export interface TicketViewTreeOptions {
    /** Prepend a flat node listing the current user's favorites. */
    includeFavorites?: boolean
    /** When set, only these views survive, along with the folders on their paths. */
    matches?: SavedTicketView[] | null
}

/**
 * Folders come from the views themselves, so a folder exists exactly while a view references it.
 * Folders sort before views, each group alphabetically — a folder is a browsing surface, so the
 * flat list's favorites-then-newest order would not help here.
 */
export function buildTicketViewTree(
    views: SavedTicketView[],
    { includeFavorites = false, matches = null }: TicketViewTreeOptions = {}
): TreeDataItem[] {
    let visible = views
    if (matches) {
        const matched = new Set(matches.map((match) => match.short_id))
        visible = views.filter((view) => matched.has(view.short_id))
    }

    const root = emptyBranch([])
    for (const view of visible) {
        let branch = root
        for (const segment of splitPath(view.folder)) {
            let child = branch.folders.get(segment)
            if (!child) {
                child = emptyBranch([...branch.segments, segment])
                branch.folders.set(segment, child)
            }
            branch = child
        }
        branch.views.push(view)
    }

    const nodes = branchToNode(root).children ?? []
    if (!includeFavorites) {
        return nodes
    }

    const favorites = visible.filter((view) => view.is_favorited).sort(byName)
    if (!favorites.length) {
        return nodes
    }
    return [
        {
            id: FAVORITES_NODE_ID,
            name: 'Favorites',
            // No path: folderPathFromNodeId returns null here, so callers can tell it apart from
            // a real folder and skip folder actions on it.
            record: { type: 'folder' },
            children: favorites.map((view) => viewNode(view, favoriteNodeId(view.short_id))),
        },
        ...nodes,
    ]
}

function countViews(item: TreeDataItem): number {
    if (item.record?.type === 'view') {
        return 1
    }
    return (item.children ?? []).reduce((total, child) => total + countViews(child), 0)
}

export interface TicketViewMenuHandlers {
    onSelectView: (view: SavedTicketView) => void
    /** Called for folders past the submenu depth cap, to hand off to a surface that can show them. */
    onBrowseFolder: (path: string) => void
}

/**
 * Each submenu level is a floating popover that shifts sideways, so beyond this depth the user is
 * chasing a popover across the viewport with no breadcrumb. Deeper folders offer a browse row instead.
 */
const MAX_MENU_DEPTH = 2

/** Nested LemonMenu items for the folder tree, capped at MAX_MENU_DEPTH levels of submenu. */
export function ticketViewMenuItems(
    items: TreeDataItem[],
    handlers: TicketViewMenuHandlers,
    depth = 1
): LemonMenuItem[] {
    return items.map((item): LemonMenuItem => {
        if (item.record?.type === 'view') {
            return { label: item.name, onClick: () => handlers.onSelectView(item.record!.view) }
        }
        const path: string = item.record?.path ?? ''
        if (depth >= MAX_MENU_DEPTH) {
            return {
                label: `Browse "${item.name}" (${countViews(item)})`,
                onClick: () => handlers.onBrowseFolder(path),
            }
        }
        return {
            label: item.name,
            items: ticketViewMenuItems(item.children ?? [], handlers, depth + 1),
        }
    })
}

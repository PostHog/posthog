import { connect, kea, path } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import type { filesSceneLogicType } from './filesSceneLogicType'

export const FILES_SCENE_LOGIC_KEY = 'files-scene'
export const filesSceneTreeProps = { key: FILES_SCENE_LOGIC_KEY, root: 'project://' }

const PROTOCOL = 'project://'

/** Syncs the file tree's expanded folders and selected item into the URL hash, so back/forward restores the tree state. */
export const filesSceneLogic = kea<filesSceneLogicType>([
    path(['scenes', 'files', 'filesSceneLogic']),
    connect(() => ({
        values: [projectTreeLogic(filesSceneTreeProps), ['expandedFolders', 'lastViewedId']],
        actions: [
            projectTreeLogic(filesSceneTreeProps),
            ['toggleFolderOpen', 'setExpandedFolders', 'loadFolderIfNotLoaded', 'setLastViewedId'],
        ],
    })),
    actionToUrl(({ values }) => {
        const syncTreeStateToUrl = ():
            | [string, Record<string, any>, Record<string, any>, { replace: boolean }]
            | void => {
            const { currentLocation } = router.values
            if (removeProjectIdIfPresent(currentLocation.pathname) !== urls.files()) {
                return
            }
            const folders = values.expandedFolders
                .filter((id) => id.startsWith(PROTOCOL) && id !== PROTOCOL)
                .map((id) => id.slice(PROTOCOL.length))
            const hashParams = { ...router.values.hashParams }
            if (folders.length > 0) {
                hashParams.folders = folders
            } else {
                delete hashParams.folders
            }
            if (values.lastViewedId) {
                hashParams.focus = values.lastViewedId
            } else {
                delete hashParams.focus
            }
            // Replace instead of push: each expand/collapse updates the current history entry,
            // so "back" leaves the page (with the final tree state preserved in its entry)
            return [currentLocation.pathname, router.values.searchParams, hashParams, { replace: true }]
        }
        return {
            toggleFolderOpen: syncTreeStateToUrl,
            setExpandedFolders: syncTreeStateToUrl,
            setLastViewedId: syncTreeStateToUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.files()]: (_, __, hashParams) => {
            const raw = hashParams['folders']
            const paths: string[] = Array.isArray(raw) ? raw.map(String) : typeof raw === 'string' && raw ? [raw] : []
            const targetIds = Array.from(new Set([PROTOCOL, ...paths.map((folder) => PROTOCOL + folder)]))
            if (!objectsEqual([...values.expandedFolders].sort(), [...targetIds].sort())) {
                actions.setExpandedFolders(targetIds)
                for (const folderId of targetIds) {
                    if (folderId !== PROTOCOL) {
                        actions.loadFolderIfNotLoaded(folderId)
                    }
                }
            }
            const focus = hashParams['focus']
            if (typeof focus === 'string' && focus && focus !== values.lastViewedId) {
                actions.setLastViewedId(focus)
            }
        },
    })),
])

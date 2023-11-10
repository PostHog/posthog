import { kea, path, listeners, connect, afterMount, beforeUnmount } from 'kea'

import { commandPaletteLogic } from '../CommandPalette/commandPaletteLogic'
import { commandBarLogic } from './commandBarLogic'

import { BarStatus } from './types'

import type { actionBarLogicType } from './actionBarLogicType'

export const actionBarLogic = kea<actionBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'actionBarLogic']),
    connect({
        actions: [
            commandBarLogic,
            ['hideCommandBar', 'setCommandBar'],
            commandPaletteLogic,
            ['showPalette', 'hidePalette', 'setInput', 'executeResult', 'backFlow', 'onArrowUp', 'onArrowDown'],
        ],
        values: [
            commandPaletteLogic,
            [
                'input',
                'activeResultIndex',
                'commandRegistrations',
                'commandSearchResults',
                'commandSearchResultsGrouped',
                'activeFlow',
            ],
        ],
    }),
    listeners(({ actions }) => ({
        hidePalette: () => {
            actions.hideCommandBar()
        },
    })),
    afterMount(({ actions, values, cache }) => {
        actions.showPalette()

        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Enter' && values.commandSearchResults.length) {
                const result = values.commandSearchResults[values.activeResultIndex]
                const isExecutable = !!result.executor
                if (isExecutable) {
                    actions.executeResult(result)
                }
            } else if (event.key === 'ArrowDown') {
                event.preventDefault()
                actions.onArrowDown(values.commandSearchResults.length - 1)
            } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                actions.onArrowUp()
            } else if (event.key === 'Escape') {
                event.preventDefault()
                // Return to previous flow
                if (values.activeFlow) {
                    actions.backFlow()
                }
                // If no flow, erase input
                else if (values.input) {
                    actions.setInput('')
                }
                // Lastly hide palette
                else {
                    actions.hidePalette()
                }
            } else if (event.key === 'Backspace') {
                if (values.input.length === 0) {
                    actions.setCommandBar(BarStatus.SHOW_SEARCH)
                }
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ actions, cache }) => {
        actions.hidePalette()

        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])

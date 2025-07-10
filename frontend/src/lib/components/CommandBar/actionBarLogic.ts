import { afterMount, beforeUnmount, connect, kea, listeners, path } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { commandPaletteLogic } from '../CommandPalette/commandPaletteLogic'
import type { actionBarLogicType } from './actionBarLogicType'
import { commandBarLogic } from './commandBarLogic'
import { BarStatus } from './types'

export const actionBarLogic = kea<actionBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'actionBarLogic']),
    connect(() => ({
        actions: [
            commandBarLogic,
            ['hideCommandBar', 'setCommandBar', 'clearInitialQuery'],
            commandPaletteLogic,
            ['showPalette', 'hidePalette', 'setInput', 'executeResult', 'backFlow', 'onArrowUp', 'onArrowDown'],
            eventUsageLogic,
            ['reportCommandBarActionSearch', 'reportCommandBarActionResultExecuted'],
        ],
        values: [
            commandBarLogic,
            ['initialQuery', 'barStatus'],
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
    })),
    listeners(({ actions }) => ({
        hidePalette: () => {
            // listen on hide action from legacy palette, and hide command bar
            actions.hideCommandBar()
        },
        setInput: ({ input }) => {
            actions.reportCommandBarActionSearch(input)
        },
        executeResult: ({ result }) => {
            actions.reportCommandBarActionResultExecuted(result.display)
        },
    })),
    subscriptions(({ values, actions }) => ({
        barStatus: (value, oldvalue) => {
            if (value !== BarStatus.SHOW_ACTIONS || oldvalue === BarStatus.SHOW_ACTIONS) {
                return
            }

            if (values.initialQuery !== null) {
                // set default query from url
                actions.setInput(values.initialQuery)
                actions.clearInitialQuery()
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        // trigger show action from legacy palette
        actions.showPalette()

        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Enter' && values.commandSearchResults.length) {
                // execute result
                const result = values.commandSearchResults[values.activeResultIndex]
                const isExecutable = !!result.executor
                if (isExecutable) {
                    actions.executeResult(result)
                }
            } else if (event.key === 'ArrowDown') {
                // navigate to next result
                event.preventDefault()
                actions.onArrowDown(values.commandSearchResults.length - 1)
            } else if (event.key === 'ArrowUp') {
                // navigate to previous result
                event.preventDefault()
                actions.onArrowUp()
            } else if (event.key === 'Escape' && event.repeat === false) {
                event.preventDefault()

                if (values.activeFlow) {
                    // return to previous flow
                    actions.backFlow()
                } else if (values.input) {
                    // or erase input
                    actions.setInput('')
                } else {
                    // or hide palette
                    actions.hidePalette()
                }
            } else if (event.key === 'Backspace') {
                if (values.input.length === 0 && event.repeat === false) {
                    // transition to search when pressing backspace with empty input
                    actions.setCommandBar(BarStatus.SHOW_SEARCH)
                }
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ actions, cache }) => {
        // trigger hide action from legacy palette
        actions.hidePalette()

        // unregister keyboard shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])

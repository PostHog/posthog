import { actions, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { HTMLProps } from 'react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import type { draggableLinkLogicType } from './draggableLinkLogicType'

export const draggableLinkLogic = kea<draggableLinkLogicType>([
    path(['lib', 'components', 'DraggableLink', 'draggableLinkLogic']),

    connect(() => ({
        values: [sidePanelStateLogic, ['sidePanelOpen', 'selectedTab'], featureFlagLogic, ['featureFlags']],
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    })),

    actions({
        startDropMode: true,
        endDropMode: true,
        setDroppedResource: (resource: string | null) => ({ resource }),
    }),

    reducers(() => ({
        dropMode: [
            false,
            {
                startDropMode: () => true,
                endDropMode: () => false,
            },
        ],
        droppedResource: [
            null as string | null,
            {
                closeSidePanel: () => null,
                setDroppedResource: (_, { resource }) => resource,
            },
        ],
    })),

    selectors(({ cache }) => ({
        dropProperties: [
            (s) => [s.dropMode],
            (dropMode): Pick<HTMLProps<HTMLDivElement>, 'onDragEnter' | 'onDragLeave' | 'style'> => {
                return dropMode
                    ? {
                          onDragEnter: () => {
                              cache.dragEntercount = (cache.dragEntercount || 0) + 1
                          },

                          onDragLeave: () => {
                              cache.dragEntercount = (cache.dragEntercount || 0) - 1

                              if (cache.dragEntercount <= 0) {
                                  cache.dragEntercount = 0
                              }
                          },
                      }
                    : {}
            },
        ],
    })),

    listeners(({ cache, actions, values }) => ({
        startDropMode: () => {
            cache.dragEntercount = 0
            // Removed automatic panel state tracking since auto-opening is disabled

            // Add drag listener using disposables
            cache.disposables.add(() => {
                const dragListener = (event: MouseEvent): void => {
                    if (!cache.dragStart) {
                        cache.dragStart = event.pageX
                    }

                    // The drop distance is the percentage between where the drag started and where it now is
                    const distanceFromRightEdge = window.innerWidth - event.pageX

                    // If we are dragging close to the side panel
                    const shouldBeOpen = distanceFromRightEdge < 200

                    // Track the last action to prevent excessive calls to the same action
                    const currentState = values.sidePanelOpen && values.selectedTab === SidePanelTab.Notebooks

                    if (shouldBeOpen && !currentState && cache.lastPanelAction !== 'open') {
                        cache.lastPanelAction = 'open'
                        actions.openSidePanel(SidePanelTab.Notebooks)
                    } else if (
                        !cache.initialPanelState.sidePanelOpen &&
                        !shouldBeOpen &&
                        cache.lastPanelAction !== 'close'
                    ) {
                        cache.lastPanelAction = 'close'
                        actions.closeSidePanel()
                    }
                }
                window.addEventListener('drag', dragListener)
                return () => window.removeEventListener('drag', dragListener)
            }, 'dragListener')
        },
        endDropMode: () => {
            // Clean up drag listener - no automatic panel state changes since we disabled auto-opening
            cache.disposables.dispose('dragListener')
        },
    })),

    beforeUnmount(({ cache }) => {
        // Clean up any active drag listener if component unmounts during drag
        if (cache.dragListener) {
            window.removeEventListener('drag', cache.dragListener)
        }
    }),
])

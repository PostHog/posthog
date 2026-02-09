import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { toolbarConfigLogic, toolbarFetch, toolbarUploadMedia } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { captureScreenshot } from '~/toolbar/utils/screenshot'
import { EventDefinition } from '~/types'

import type { screenshotUploadLogicType } from './screenshotUploadLogicType'

export interface ScreenshotUploadLogicProps {
    onSuccess?: () => void
}

export const screenshotUploadLogic = kea<screenshotUploadLogicType>([
    path(['toolbar', 'screenshot-upload', 'screenshotUploadLogic']),
    props({} as ScreenshotUploadLogicProps),

    actions({
        setEventName: (name: string) => ({ name }),
        selectEvent: (definition: EventDefinition) => ({ definition }),
        setShowSuggestions: (show: boolean) => ({ show }),
        takeScreenshot: true,
        openModal: (screenshot: Blob) => ({ screenshot }),
        closeModal: true,
    }),

    reducers({
        isTakingScreenshot: [false, { takeScreenshot: () => true, openModal: () => false }],
        isModalOpen: [false, { openModal: () => true, closeModal: () => false }],
        screenshot: [null as Blob | null, { openModal: (_, { screenshot }) => screenshot, closeModal: () => null }],
        eventName: [
            '',
            {
                setEventName: (_, { name }) => name,
                selectEvent: (_, { definition }) => definition.name,
                closeModal: () => '',
            },
        ],
        selectedDefinition: [
            null as EventDefinition | null,
            {
                selectEvent: (_, { definition }) => definition,
                setEventName: () => null,
                closeModal: () => null,
            },
        ],
        showSuggestions: [
            false,
            {
                setShowSuggestions: (_, { show }) => show,
                selectEvent: () => false,
                closeModal: () => false,
            },
        ],
    }),

    loaders({
        eventDefinitions: [
            [] as EventDefinition[],
            {
                searchEvents: async ({ query }: { query: string }, breakpoint) => {
                    if (!query.trim()) {
                        return []
                    }
                    await breakpoint(300)
                    const response = await toolbarFetch(
                        `/api/projects/@current/event_definitions/?search=${encodeURIComponent(query)}&limit=20`
                    )

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()
                    const data = await response.json()
                    return data.results ?? []
                },
            },
        ],
        uploadResult: [
            null as null | { success: boolean },
            {
                submitUpload: async (_, breakpoint) => {
                    const { screenshot, selectedDefinition } = screenshotUploadLogic.values
                    if (!screenshot || !selectedDefinition) {
                        lemonToast.error('Please select an event')
                        return null
                    }

                    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
                    const file = new File([screenshot], `screenshot-${timestamp}.png`, { type: 'image/png' })
                    const uploaded = await toolbarUploadMedia(file)
                    breakpoint()

                    await toolbarFetch('/api/projects/@current/object_media_previews', 'POST', {
                        uploaded_media_id: uploaded.id,
                        event_definition_id: selectedDefinition.id,
                    })
                    breakpoint()

                    return { success: true }
                },
            },
        ],
    }),

    selectors({
        previewUrl: [
            (s) => [s.screenshot],
            (screenshot): string | null => (screenshot ? URL.createObjectURL(screenshot) : null),
        ],
    }),

    listeners(({ actions, props }) => ({
        takeScreenshot: async () => {
            const blob = await captureScreenshot()
            if (blob) {
                actions.openModal(blob)
            }
        },
        setEventName: ({ name }) => {
            actions.setShowSuggestions(name.length > 0)
            actions.searchEvents({ query: name })
        },
        submitUploadSuccess: () => {
            toolbarPosthogJS.capture('media preview uploaded', { source: 'toolbar' })
            lemonToast.success('Screenshot uploaded successfully')
            actions.closeModal()
            props.onSuccess?.()
        },
        submitUploadFailure: ({ error }) => {
            lemonToast.error(`Failed to upload screenshot: ${error}`)
        },
    })),
])

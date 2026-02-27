import { actions, kea, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { captureElementScreenshot, uploadScreenshot } from '~/toolbar/utils/screenshot'
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
        openModal: (previewUrl: string) => ({ previewUrl }),
        closeModal: true,
    }),

    reducers({
        isTakingScreenshot: [false, { takeScreenshot: () => true, openModal: () => false }],
        isModalOpen: [false, { openModal: () => true, closeModal: () => false }],
        previewUrl: [null as string | null, { openModal: (_, { previewUrl }) => previewUrl, closeModal: () => null }],
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
                        `/api/projects/@current/event_definitions/?search=${encodeURIComponent(query)}&limit=20&event_type=event_custom`
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
                    const { previewUrl, selectedDefinition } = screenshotUploadLogic.values
                    if (!previewUrl || !selectedDefinition) {
                        lemonToast.error('Please select an event')
                        return null
                    }

                    const blob = await fetch(previewUrl).then((r) => r.blob())
                    const { mediaId } = await uploadScreenshot(blob)
                    breakpoint()

                    await toolbarFetch('/api/projects/@current/object_media_previews/', 'POST', {
                        uploaded_media_id: mediaId,
                        event_definition_id: selectedDefinition.id,
                    })
                    breakpoint()

                    return { success: true }
                },
            },
        ],
    }),

    listeners(({ actions, props, values }) => ({
        takeScreenshot: async () => {
            const blob = await captureElementScreenshot(document.documentElement)
            actions.openModal(URL.createObjectURL(blob))
        },
        closeModal: () => {
            if (values.previewUrl) {
                URL.revokeObjectURL(values.previewUrl)
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

import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { inferSelector } from '~/toolbar/product-tours/elementInference'
import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarRequestError } from '~/toolbar/toolbarRequestError'
import { ElementRect } from '~/toolbar/types'
import { TOOLBAR_ID, elementToActionStep, getRectForElement, joinWithUiHost } from '~/toolbar/utils'
import { captureAndUploadElementScreenshot } from '~/toolbar/utils/screenshot'

import type { fieldNotesLogicType } from './fieldNotesLogicType'

export interface PageContext {
    url: string
    host: string
    pathname: string
    viewport: { width: number; height: number }
}

function capturePageContext(): PageContext {
    // Drop the query string and fragment — they can carry one-time tokens (reset, OAuth, session)
    // that would otherwise be persisted and surfaced to anyone with field note read access.
    return {
        url: `${window.location.origin}${window.location.pathname}`,
        host: window.location.host,
        pathname: window.location.pathname,
        viewport: { width: window.innerWidth, height: window.innerHeight },
    }
}

export interface FieldNote {
    id: string
    comment: string
    field_note_status: 'pending' | 'acknowledged' | 'resolved' | 'dismissed'
    resolution: string | null
    url: string
    host: string
    pathname: string | null
    selector: string
    element_text: string | null
    screenshot_url: string | null
    created_at: string
}

function isToolbarElement(element: HTMLElement): boolean {
    const toolbar = document.getElementById(TOOLBAR_ID)
    return toolbar?.contains(element) ?? false
}

export const fieldNotesLogic = kea<fieldNotesLogicType>([
    path(['toolbar', 'field-notes', 'fieldNotesLogic']),

    connect(() => ({
        values: [toolbarConfigLogic, ['dataAttributes', 'uiHost']],
    })),

    actions({
        showButtonFieldNotes: true,
        hideButtonFieldNotes: true,
        startFieldNote: true,
        stopFieldNote: true,
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        // Snapshot the page context at select time — on an SPA the URL can change before save.
        selectElement: (element: HTMLElement) => ({ element, page: capturePageContext() }),
        clearSelection: true,
        setComment: (comment: string) => ({ comment }),
        setScreenshotUrl: (url: string | null) => ({ url }),
        deleteFieldNote: (id: string) => ({ id }),
        updateRects: true,
    }),

    loaders(({ values }) => ({
        fieldNotes: [
            [] as FieldNote[],
            {
                loadFieldNotes: async () => {
                    const result = await toolbarApi.fieldNotes.listPending<{ results?: FieldNote[] } | FieldNote[]>({
                        context: 'load_field_notes',
                    })
                    if (!result.ok) {
                        return values.fieldNotes
                    }
                    return Array.isArray(result.data) ? result.data : (result.data.results ?? [])
                },
            },
        ],
    })),

    reducers({
        buttonFieldNotesVisible: [
            false,
            {
                showButtonFieldNotes: () => true,
                hideButtonFieldNotes: () => false,
            },
        ],
        isFieldNoting: [
            false,
            {
                startFieldNote: () => true,
                stopFieldNote: () => false,
                selectElement: () => false,
                hideButtonFieldNotes: () => false,
            },
        ],
        hoverElement: [
            null as HTMLElement | null,
            {
                setHoverElement: (_, { element }) => element,
                stopFieldNote: () => null,
                selectElement: () => null,
                hideButtonFieldNotes: () => null,
            },
        ],
        selectedElement: [
            null as HTMLElement | null,
            {
                selectElement: (_, { element }) => element,
                clearSelection: () => null,
                // Closing/switching the menu closes the comment box (no cascade: select no longer calls setVisibleMenu).
                hideButtonFieldNotes: () => null,
            },
        ],
        comment: [
            '',
            {
                setComment: (_, { comment }) => comment,
                clearSelection: () => '',
                hideButtonFieldNotes: () => '',
                submitFieldNoteSuccess: () => '',
            },
        ],
        pageContext: [
            null as PageContext | null,
            {
                selectElement: (_, { page }) => page,
                clearSelection: () => null,
                hideButtonFieldNotes: () => null,
            },
        ],
        screenshotUrl: [
            null as string | null,
            {
                setScreenshotUrl: (_, { url }) => url,
                selectElement: () => null,
                clearSelection: () => null,
                hideButtonFieldNotes: () => null,
            },
        ],
        rectUpdateCounter: [
            0,
            {
                updateRects: (state) => state + 1,
            },
        ],
        // Drives the "new" badge on the toolbar button — dismissed (persistently) once the menu is first opened.
        hasOpenedFieldNotes: [
            false,
            { persist: true },
            {
                showButtonFieldNotes: () => true,
            },
        ],
        // Id of the field note currently being deleted, to disable its row button (no double-submit).
        deletingId: [
            null as string | null,
            {
                deleteFieldNote: (_, { id }) => id,
                loadFieldNotesSuccess: () => null,
                loadFieldNotesFailure: () => null,
            },
        ],
    }),

    selectors({
        hoverElementRect: [
            (s) => [s.hoverElement, s.rectUpdateCounter],
            (hoverElement): ElementRect | null => (hoverElement ? getRectForElement(hoverElement) : null),
        ],
        selectedElementRect: [
            (s) => [s.selectedElement, s.rectUpdateCounter],
            (selectedElement): ElementRect | null => (selectedElement ? getRectForElement(selectedElement) : null),
        ],
    }),

    loaders(({ values, actions }) => ({
        submitResult: [
            null as FieldNote | null,
            {
                submitFieldNote: async () => {
                    const { selectedElement, comment, dataAttributes, pageContext, screenshotUrl } = values
                    if (!selectedElement || !comment.trim()) {
                        return null
                    }
                    const selector = elementToActionStep(selectedElement, dataAttributes).selector ?? ''
                    const inferred = inferSelector(selectedElement)?.selector
                    const elementText = (selectedElement.textContent ?? '').trim().slice(0, 500) || null
                    const page = pageContext ?? capturePageContext()

                    const payload = {
                        comment: comment.trim(),
                        url: page.url,
                        host: page.host,
                        pathname: page.pathname,
                        selector,
                        element_text: elementText,
                        element_context: inferred ? { inferred } : {},
                        viewport: page.viewport,
                        ...(screenshotUrl ? { screenshot_url: screenshotUrl } : {}),
                    }

                    const result = await toolbarApi.fieldNotes.create<FieldNote>(payload, {
                        context: 'save_field_note',
                        toastOnError: 'Failed to save field note',
                    })
                    if (!result.ok) {
                        return null
                    }
                    lemonToast.success('Field note saved')
                    actions.clearSelection()
                    actions.loadFieldNotes()
                    return result.data
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        showButtonFieldNotes: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'field-notes', enabled: true })
            actions.loadFieldNotes()
        },
        hideButtonFieldNotes: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'field-notes', enabled: false })
        },
        // Capture a screenshot in the background while the user types — best-effort, never blocks save.
        selectElement: async ({ element }) => {
            try {
                const { mediaId } = await captureAndUploadElementScreenshot(element)
                actions.setScreenshotUrl(joinWithUiHost(values.uiHost, `/uploaded_media/${mediaId}`))
            } catch (e: any) {
                toolbarLogger.warn('field-notes', 'Failed to capture screenshot')
                // A failed upload request (ToolbarRequestError) is expected; only a bug in
                // the screenshot capture itself is worth an exception.
                if (!(e instanceof ToolbarRequestError)) {
                    captureToolbarException(e, 'field_note_screenshot')
                }
            }
        },
        deleteFieldNote: async ({ id }) => {
            await toolbarApi.fieldNotes.delete(id, {
                context: 'delete_field_note',
                toastOnError: 'Failed to delete field note',
            })
            actions.loadFieldNotes()
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            cache.onMouseOver = (e: MouseEvent): void => {
                if (!values.isFieldNoting) {
                    return
                }
                const target = e.target as HTMLElement
                if (target && !isToolbarElement(target)) {
                    actions.setHoverElement(target)
                }
            }
            cache.onClick = (e: MouseEvent): void => {
                if (!values.isFieldNoting) {
                    return
                }
                const target = e.target as HTMLElement
                if (!target || isToolbarElement(target)) {
                    return
                }
                e.preventDefault()
                e.stopPropagation()
                actions.selectElement(target)
            }
            cache.onScroll = (): void => {
                if (values.hoverElement || values.selectedElement) {
                    actions.updateRects()
                }
            }
            cache.onResize = (): void => {
                if (values.hoverElement || values.selectedElement) {
                    actions.updateRects()
                }
            }
            cache.onKeyDown = (e: KeyboardEvent): void => {
                if (e.key === 'Escape' && values.isFieldNoting) {
                    actions.stopFieldNote()
                }
            }
            document.addEventListener('mouseover', cache.onMouseOver, true)
            document.addEventListener('click', cache.onClick, true)
            document.addEventListener('scroll', cache.onScroll, { capture: true, passive: true })
            window.addEventListener('resize', cache.onResize)
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            if (cache.onMouseOver) {
                document.removeEventListener('mouseover', cache.onMouseOver, true)
            }
            if (cache.onClick) {
                document.removeEventListener('click', cache.onClick, true)
            }
            if (cache.onScroll) {
                document.removeEventListener('scroll', cache.onScroll, { capture: true })
            }
            if (cache.onResize) {
                window.removeEventListener('resize', cache.onResize)
            }
            if (cache.onKeyDown) {
                window.removeEventListener('keydown', cache.onKeyDown)
            }
        },
    })),
])

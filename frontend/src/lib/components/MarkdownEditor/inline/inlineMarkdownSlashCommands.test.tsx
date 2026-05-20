import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Editor } from '@tiptap/core'
import { createRef, type ComponentRef } from 'react'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { initKeaTests } from '~/test/init'
import { Realm, type PreflightStatus } from '~/types'

import {
    DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS,
    InlineMarkdownSlashMenu,
    type InlineMarkdownSlashCommandItem,
} from './inlineMarkdownSlashCommands'

const PREFLIGHT_WITH_OBJECT_STORAGE = {
    django: true,
    plugins: true,
    redis: true,
    db: true,
    clickhouse: true,
    kafka: true,
    initiated: true,
    can_create_org: true,
    cloud: false,
    demo: false,
    celery: true,
    realm: Realm.SelfHostedClickHouse,
    region: null,
    available_social_auth_providers: {},
    email_service_available: false,
    slack_service: { available: false },
    posthog_code_slack_service: { available: false },
    data_warehouse_integrations: { hubspot: {}, salesforce: {} },
    object_storage: true,
} satisfies PreflightStatus

const PREFLIGHT_WITHOUT_OBJECT_STORAGE: PreflightStatus = {
    ...PREFLIGHT_WITH_OBJECT_STORAGE,
    object_storage: false,
}

function makeEditorWithChain(chainApi: {
    focus: () => typeof chainApi
    deleteRange: () => { run: () => boolean }
}): Editor {
    return {
        chain: () => chainApi,
    } as unknown as Editor
}

describe('InlineMarkdownSlashMenu', () => {
    beforeEach(() => {
        initKeaTests()
        preflightLogic.actions.loadPreflightSuccess(PREFLIGHT_WITH_OBJECT_STORAGE)
    })

    afterEach(() => {
        cleanup()
    })

    it('renders Style and Insert section labels for default commands', () => {
        const editor = makeEditorWithChain({
            focus() {
                return this
            },
            deleteRange: () => ({ run: () => true }),
        })

        render(
            <InlineMarkdownSlashMenu
                editor={editor}
                range={{ from: 0, to: 1 }}
                query=""
                commands={DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS}
                slashImageHostRef={{ current: { pick: () => {}, showSlashImageUpload: true } }}
            />
        )

        expect(screen.getByText('Style')).toBeInTheDocument()
        expect(screen.getByText('Insert')).toBeInTheDocument()
    })

    it('filters commands by query', () => {
        const editor = makeEditorWithChain({
            focus() {
                return this
            },
            deleteRange: () => ({ run: () => true }),
        })

        render(
            <InlineMarkdownSlashMenu
                editor={editor}
                range={{ from: 0, to: 1 }}
                query="bold"
                commands={DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS}
                slashImageHostRef={{ current: { pick: () => {}, showSlashImageUpload: true } }}
            />
        )

        expect(screen.getByRole('button', { name: /Bold/i })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /Image/i })).not.toBeInTheDocument()
    })

    it('hides the Image row when slash image upload is disabled on the host ref', () => {
        const editor = makeEditorWithChain({
            focus() {
                return this
            },
            deleteRange: () => ({ run: () => true }),
        })

        render(
            <InlineMarkdownSlashMenu
                editor={editor}
                range={{ from: 0, to: 1 }}
                query=""
                commands={DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS}
                slashImageHostRef={{ current: { pick: () => {}, showSlashImageUpload: false } }}
            />
        )

        expect(screen.queryByRole('button', { name: /Image/i })).not.toBeInTheDocument()
    })

    it('disables Image when object storage is not available', () => {
        preflightLogic.actions.loadPreflightSuccess(PREFLIGHT_WITHOUT_OBJECT_STORAGE)

        const editor = makeEditorWithChain({
            focus() {
                return this
            },
            deleteRange: () => ({ run: () => true }),
        })

        render(
            <InlineMarkdownSlashMenu
                editor={editor}
                range={{ from: 0, to: 1 }}
                query="image"
                commands={DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS}
                slashImageHostRef={{ current: { pick: () => {}, showSlashImageUpload: true } }}
            />
        )

        const imageRow = screen.getByRole('button', { name: /Image/i })
        expect(imageRow).toHaveAttribute('aria-disabled', 'true')
    })

    it('clamps keyboard selection when the Image row disappears without a query change', () => {
        const slashImageHostRef = { current: { pick: jest.fn(), showSlashImageUpload: true } }
        const testCommands: InlineMarkdownSlashCommandItem[] = [
            {
                title: 'Alpha',
                description: 'a',
                icon: <span aria-hidden>a</span>,
                section: 'Style',
                command: () => {},
            },
            {
                title: 'Beta',
                description: 'b',
                icon: <span aria-hidden>b</span>,
                section: 'Style',
                command: () => {},
            },
            {
                title: 'Gamma',
                description: 'c',
                icon: <span aria-hidden>c</span>,
                section: 'Style',
                command: () => {},
            },
            {
                title: 'Image',
                description: 'img',
                icon: <span aria-hidden>i</span>,
                section: 'Insert',
                isImagePick: true,
                command: () => {},
            },
        ]

        const editor = makeEditorWithChain({
            focus() {
                return this
            },
            deleteRange: () => ({ run: () => true }),
        })

        const menuRef = createRef<ComponentRef<typeof InlineMarkdownSlashMenu>>()
        const { rerender } = render(
            <InlineMarkdownSlashMenu
                ref={menuRef}
                editor={editor}
                range={{ from: 0, to: 1 }}
                query=""
                commands={testCommands}
                slashImageHostRef={slashImageHostRef}
            />
        )

        const down = { key: 'ArrowDown' } as KeyboardEvent
        for (let i = 0; i < 3; i++) {
            act(() => {
                menuRef.current?.onKeyDown(down)
            })
        }

        expect(screen.getByRole('button', { name: /Image/i })).toHaveClass('LemonButton--active')

        slashImageHostRef.current.showSlashImageUpload = false
        rerender(
            <InlineMarkdownSlashMenu
                ref={menuRef}
                editor={editor}
                range={{ from: 0, to: 1 }}
                query=""
                commands={testCommands}
                slashImageHostRef={slashImageHostRef}
            />
        )

        expect(screen.queryByRole('button', { name: /Image/i })).not.toBeInTheDocument()
        expect(screen.getByRole('button', { name: /Gamma/i })).toHaveClass('LemonButton--active')
    })

    it('choosing Image deletes the slash range and opens the host picker', () => {
        const pick = jest.fn()
        const deleteRun = jest.fn(() => true)
        const chainApi = {
            focus() {
                return this
            },
            deleteRange: () => ({ run: deleteRun }),
        }
        const editor = makeEditorWithChain(chainApi)
        const onClose = jest.fn()
        const raf = jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
            cb(0)
            return 0
        })

        render(
            <InlineMarkdownSlashMenu
                editor={editor}
                range={{ from: 2, to: 5 }}
                query="image"
                onClose={onClose}
                commands={DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS}
                slashImageHostRef={{ current: { pick, showSlashImageUpload: true } }}
            />
        )

        fireEvent.click(screen.getByRole('button', { name: /Image/i }))

        expect(deleteRun).toHaveBeenCalled()
        expect(onClose).toHaveBeenCalled()
        expect(pick).toHaveBeenCalled()

        raf.mockRestore()
    })

    it('choosing Link deletes the slash range and opens the host link popover', () => {
        const openLinkPopover = jest.fn()
        const deleteRun = jest.fn(() => true)
        const chainApi = {
            focus() {
                return this
            },
            deleteRange: () => ({ run: deleteRun }),
        }
        const editor = makeEditorWithChain(chainApi)
        const onClose = jest.fn()
        const raf = jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
            cb(0)
            return 0
        })

        render(
            <InlineMarkdownSlashMenu
                editor={editor}
                range={{ from: 2, to: 5 }}
                query="link"
                onClose={onClose}
                commands={DEFAULT_INLINE_MARKDOWN_SLASH_COMMANDS}
                slashLinkHostRef={{ current: { openLinkPopover } }}
            />
        )

        fireEvent.click(screen.getByRole('button', { name: /Link/i }))

        expect(deleteRun).toHaveBeenCalled()
        expect(onClose).toHaveBeenCalled()
        expect(openLinkPopover).toHaveBeenCalled()

        raf.mockRestore()
    })
})

import type { Meta, StoryObj } from '@storybook/react'

import { CheckIcon, FileIcon, PencilIcon, SearchIcon, TerminalIcon } from 'lucide-react'

import { ChatMarker, ChatMarkerContent, ChatMarkerIcon } from './chat-marker'
import { Spinner } from '../spinner'

const meta = {
    title: 'Primitives/Chat/ChatMarker',
    component: ChatMarker,
    tags: ['autodocs'],
} satisfies Meta<typeof ChatMarker>

export default meta
type Story = StoryObj<typeof meta>

/** The three flat variants — no body, no collapse (stock shadcn Marker). */
export const Variants = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatMarker>
                <ChatMarkerIcon>
                    <CheckIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Explored 4 files</ChatMarkerContent>
            </ChatMarker>
            <ChatMarker variant="border">
                <ChatMarkerIcon>
                    <SearchIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Searched the workspace</ChatMarkerContent>
            </ChatMarker>
            <ChatMarker variant="separator">
                <ChatMarkerContent>Context compacted</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

/** Live state: Spinner + shimmer text while a tool runs. */
export const Live = {
    render: () => (
        <div className="w-[420px]">
            <ChatMarker>
                <ChatMarkerIcon>
                    <Spinner />
                </ChatMarkerIcon>
                <ChatMarkerContent className="shimmer">Editing components/thread.tsx…</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

/**
 * Collapsible: pass `body` and the row gains a hover chevron + `bg-fill-hover`; click toggles.
 * This is the tool-group summary → per-tool children pattern. `defaultOpen` is the app's
 * grouping-mode decision (compact → false).
 */
export const Collapsible = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatMarker
                defaultOpen={false}
                body={
                    <>
                        <ChatMarker>
                            <ChatMarkerIcon>
                                <FileIcon />
                            </ChatMarkerIcon>
                            <ChatMarkerContent>Read store.ts</ChatMarkerContent>
                        </ChatMarker>
                        <ChatMarker>
                            <ChatMarkerIcon>
                                <FileIcon />
                            </ChatMarkerIcon>
                            <ChatMarkerContent>Read view.tsx</ChatMarkerContent>
                        </ChatMarker>
                        <ChatMarker>
                            <ChatMarkerIcon>
                                <PencilIcon />
                            </ChatMarkerIcon>
                            <ChatMarkerContent>Edited view.tsx</ChatMarkerContent>
                        </ChatMarker>
                    </>
                }
            >
                <ChatMarkerIcon>
                    <CheckIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Read 2 files · Edited 1 file</ChatMarkerContent>
            </ChatMarker>

            <ChatMarker
                defaultOpen
                body={
                    <ChatMarker>
                        <ChatMarkerIcon>
                            <TerminalIcon />
                        </ChatMarkerIcon>
                        <ChatMarkerContent>pnpm build — exit 0</ChatMarkerContent>
                    </ChatMarker>
                }
            >
                <ChatMarkerIcon>
                    <TerminalIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Ran 1 command (expanded by default)</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
} satisfies Story

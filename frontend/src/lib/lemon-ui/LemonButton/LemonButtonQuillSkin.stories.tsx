import type { Meta, StoryObj } from '@storybook/react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { Button as QuillButton } from '@posthog/quill'

import { LemonButton } from './LemonButton'

/**
 * Prototypes of the two possible "skin bridge" migration directions:
 *
 * - `SideBySide` (quill-skin.scss): LemonButton restyled to quill's visual
 *   language — ship the new look first, migrate code later.
 * - `ReverseSideBySide` (lemon-skin.scss): quill Button restyled to Lemon's
 *   current look — migrate code invisibly first, flip the look at the end.
 *
 * In both stories the middle column renders the exact same code as its
 * reference column — only the skin wrapper attribute differs.
 */
const meta: Meta = {
    title: 'Lemon UI/Lemon Button Quill Skin',
    parameters: {
        testOptions: {
            // The story intentionally shows always-loading buttons, whose spinners
            // would otherwise time out the snapshot runner's loader wait
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta

function LemonExamples(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 items-start">
            <LemonButton type="primary">Primary</LemonButton>
            <LemonButton type="secondary">Secondary</LemonButton>
            <LemonButton type="tertiary">Tertiary</LemonButton>
            <LemonButton type="primary" icon={<IconPlus />}>
                With icon
            </LemonButton>
            <LemonButton type="secondary" status="danger" icon={<IconTrash />}>
                Danger
            </LemonButton>
            <LemonButton type="tertiary" status="danger">
                Danger tertiary
            </LemonButton>
            <LemonButton type="primary" disabledReason="Disabled for demo purposes">
                Disabled
            </LemonButton>
            <LemonButton type="primary" loading>
                Loading
            </LemonButton>
            <div className="flex gap-2 items-center">
                <LemonButton type="secondary" size="xsmall">
                    xsmall
                </LemonButton>
                <LemonButton type="secondary" size="small">
                    small
                </LemonButton>
                <LemonButton type="secondary">medium</LemonButton>
                <LemonButton type="secondary" size="large">
                    large
                </LemonButton>
            </div>
        </div>
    )
}

function QuillExamples(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 items-start">
            <QuillButton variant="primary">Primary</QuillButton>
            <QuillButton variant="outline">Secondary</QuillButton>
            <QuillButton variant="default">Tertiary</QuillButton>
            <QuillButton variant="primary">
                <IconPlus />
                With icon
            </QuillButton>
            <QuillButton variant="destructive">
                <IconTrash />
                Danger
            </QuillButton>
            <QuillButton variant="destructive">Danger tertiary</QuillButton>
            <QuillButton variant="primary" disabled>
                Disabled
            </QuillButton>
            <QuillButton variant="primary" loading>
                Loading
            </QuillButton>
            <div className="flex gap-2 items-center">
                <QuillButton variant="outline" size="xs">
                    xsmall
                </QuillButton>
                <QuillButton variant="outline" size="sm">
                    small
                </QuillButton>
                <QuillButton variant="outline">medium</QuillButton>
                <QuillButton variant="outline" size="lg">
                    large
                </QuillButton>
            </div>
        </div>
    )
}

export const SideBySide: StoryObj = {
    render: () => (
        <div className="grid grid-cols-3 gap-4">
            <div className="border rounded p-4">
                <h4 className="mb-4">LemonButton today</h4>
                <LemonExamples />
            </div>
            <div className="border rounded p-4" data-quill data-quill-skin>
                <h4 className="mb-4">LemonButton + quill skin (same code)</h4>
                <LemonExamples />
            </div>
            <div className="border rounded p-4" data-quill>
                <h4 className="mb-4">Quill Button (target)</h4>
                <QuillExamples />
            </div>
        </div>
    ),
}

export const ReverseSideBySide: StoryObj = {
    render: () => (
        <div className="grid grid-cols-3 gap-4">
            <div className="border rounded p-4" data-quill>
                <h4 className="mb-4">Quill Button today</h4>
                <QuillExamples />
            </div>
            <div className="border rounded p-4" data-quill data-lemon-skin>
                <h4 className="mb-4">Quill Button + lemon skin (same code)</h4>
                <QuillExamples />
            </div>
            <div className="border rounded p-4">
                <h4 className="mb-4">LemonButton (target)</h4>
                <LemonExamples />
            </div>
        </div>
    ),
}

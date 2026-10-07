import type { Meta, StoryObj } from '@storybook/react'

import { NodeKindGlyph } from './NodeKindGlyph'

const meta: Meta<typeof NodeKindGlyph> = {
    title: 'Scenes-App/AI observability/Trace view/Node kind glyph',
    component: NodeKindGlyph,
}
export default meta

export const AllKinds: StoryObj<typeof NodeKindGlyph> = {
    render: () => (
        <div className="flex gap-2 items-center">
            <NodeKindGlyph kind="trace" />
            <NodeKindGlyph kind="span" />
            <NodeKindGlyph kind="generation" />
            <NodeKindGlyph kind="embedding" />
            <NodeKindGlyph kind="generation" size="medium" />
        </div>
    ),
}

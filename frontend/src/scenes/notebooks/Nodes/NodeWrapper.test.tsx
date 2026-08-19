import { render } from '@testing-library/react'

import { NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import { createPostHogWidgetNode } from './NodeWrapper'

describe('createPostHogWidgetNode', () => {
    it('renders the named view and falls back to the default component for unknown views', () => {
        const nodeType = 'ph-test-widget-views' as NotebookNodeType
        const registeredNode = createPostHogWidgetNode<{ view?: string }>({
            nodeType,
            titlePlaceholder: 'Test widget',
            Component: () => <div>Default view</div>,
            ToolbarComponent: () => <div>Toolbar metadata</div>,
            attributes: { view: {} },
            views: {
                compact: {
                    label: 'Compact',
                    Component: () => <div>Compact view</div>,
                },
            },
        })

        try {
            const compact = render(
                <registeredNode.Component
                    attributes={{ nodeId: 'compact-node', view: 'compact' }}
                    updateAttributes={jest.fn()}
                />
            )
            expect(compact.getByText('Compact view')).toBeTruthy()
            expect(compact.getByText('Toolbar metadata')).toBeTruthy()
            compact.unmount()

            const unknown = render(
                <registeredNode.Component
                    attributes={{ nodeId: 'unknown-node', view: 'unknown' }}
                    updateAttributes={jest.fn()}
                />
            )
            expect(unknown.getByText('Default view')).toBeTruthy()
            expect(unknown.getByText('Toolbar metadata')).toBeTruthy()
        } finally {
            delete KNOWN_NODES[nodeType]
        }
    })
})

import { render } from '@testing-library/react'

import { NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import {
    NOTEBOOK_MARKDOWN_REGISTRY,
    RealNotebookNodeEdit,
    getEditableNodeAttributeKeys,
    getMarkdownNodeAttributeLabel,
    getSerializableAttributeInputValue,
} from './markdownNotebookRegistry'

describe('markdownNotebookRegistry', () => {
    it('does not make real notebook nodes mutually exclusive in markdown notebooks', () => {
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.Recording.exclusiveEditPanel).toBeUndefined()
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.FeatureFlag.exclusiveEditPanel).toBeUndefined()
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.FeatureFlagCodeExample.exclusiveEditPanel).toBeUndefined()
    })

    it('renders a lightweight feature flag reference editor instead of the full node view', () => {
        const { getByLabelText } = render(
            <RealNotebookNodeEdit
                node={{
                    id: 'feature-flag-node',
                    type: 'component',
                    tagName: 'FeatureFlag',
                    props: { id: 123 },
                }}
                mode="edit"
                updateProps={jest.fn()}
                deleteNode={jest.fn()}
            />
        )

        expect((getByLabelText('Feature flag ID or key') as HTMLInputElement).value).toEqual('123')
    })

    it('exposes lightweight editable primitive attrs for real notebook node filters', () => {
        expect(
            getEditableNodeAttributeKeys(KNOWN_NODES[NotebookNodeType.FeatureFlag], {
                id: 123,
            })
        ).toEqual(['id'])
        expect(
            getEditableNodeAttributeKeys(KNOWN_NODES[NotebookNodeType.Group], {
                groupTypeIndex: 0,
                id: 'org_123',
                placement: 'feed',
                tabId: 'properties',
            })
        ).toEqual(['id', 'groupTypeIndex'])
    })

    it('uses product-specific labels for common reference attrs', () => {
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.FeatureFlag, 'id')).toEqual('Feature flag ID or key')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.Group, 'groupTypeIndex')).toEqual('Group type index')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.Person, 'distinctId')).toEqual('Distinct ID')
    })

    it('keeps numeric attrs numeric when edited through markdown filters', () => {
        expect(getSerializableAttributeInputValue(NotebookNodeType.Cohort, 'id', '123')).toEqual(123)
        expect(getSerializableAttributeInputValue(NotebookNodeType.Group, 'groupTypeIndex', '2')).toEqual(2)
        expect(getSerializableAttributeInputValue(NotebookNodeType.FeatureFlag, 'id', 'flag-key')).toEqual('flag-key')
    })
})

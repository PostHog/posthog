import { fireEvent, render, screen, within } from '@testing-library/react'

import {
    buildInsertCommands,
    getMarkdownNotebookDefaultRegistry,
    mergeMarkdownNotebookRegistries,
    omitInsertCommands,
} from 'lib/components/MarkdownNotebook'
import {
    type ComponentPanelVisibility,
    getInsertedComponentPanelVisibility,
} from 'lib/components/MarkdownNotebook/componentPanels'
import { NotebookComponentShell } from 'lib/components/MarkdownNotebook/NotebookComponentShell'
import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import notebookWidgetCatalog from 'products/notebooks/notebook-widget-catalog.json'

import { NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import {
    NOTEBOOK_MARKDOWN_REGISTRY,
    RealNotebookNodeEdit,
    RealNotebookNodeIdentityAndViewEdit,
    getEditableNodeAttributeKeys,
    getHiddenInsertCommandKeysForFeatureFlags,
    getMarkdownNodeAttributeLabel,
    getMarkdownRegistryForFeatureFlags,
    getNodeAttributes,
    getQueryTitle,
    getSerializableAttributeInputValue,
} from './markdownNotebookRegistry'

jest.mock('./MarkdownNotebookEntityPicker', () => ({
    MarkdownNotebookEntityPicker: ({ kind, onSelect }: { kind: string | null; onSelect: (value: unknown) => void }) =>
        kind ? (
            <button
                aria-label={`Pick from ${kind}`}
                onClick={() => onSelect({ tagName: 'FeatureFlag', props: { id: 999 } })}
            />
        ) : null,
}))

// Mirrors how MarkdownNotebook composes its menu, so the assertions cover the list a user sees
// rather than the registry alone: built-in commands are not registry entries, so a node hidden
// from the registry can still reach the menu through a built-in that inserts the same tag.
function getInsertCommandsByLabel(featureFlags: FeatureFlagsSet, label: string): { key: string; category: string }[] {
    const noop = (): void => {}
    const commands = omitInsertCommands(
        buildInsertCommands(
            mergeMarkdownNotebookRegistries(
                getMarkdownNotebookDefaultRegistry(),
                getMarkdownRegistryForFeatureFlags(featureFlags)
            ),
            noop,
            noop,
            noop,
            noop,
            noop
        ),
        getHiddenInsertCommandKeysForFeatureFlags(featureFlags)
    )

    return commands
        .filter((command) => command.label === label)
        .map((command) => ({ key: command.key, category: command.category }))
}

describe('markdownNotebookRegistry', () => {
    describe('getMarkdownRegistryForFeatureFlags', () => {
        it('offers a single SQL and Python cell, gated by the revamped notebooks flag', () => {
            // The unified insert surface: SQLV2 ("SQL") and PythonV2 ("Python") are the only
            // insertable code cells with the flag on; the legacy SQL/Python cells and the
            // legacy query node render but must never be insertable in markdown notebooks.
            const flagOn = getMarkdownRegistryForFeatureFlags({ [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]: true })
            expect(flagOn.components.SQLV2.insertCommand).toBeTruthy()
            expect(flagOn.components.PythonV2.insertCommand).toBeTruthy()
            for (const legacyTag of ['Query', 'Python', 'DuckSQL', 'HogQLSQL']) {
                expect(flagOn.components[legacyTag].insertCommand).toBeUndefined()
            }

            const flagOff = getMarkdownRegistryForFeatureFlags({})
            expect(flagOff.components.SQLV2.insertCommand).toBeUndefined()
            expect(flagOff.components.PythonV2.insertCommand).toBeUndefined()
        })

        // An inserted code cell holds no code and no result, so a closed editor panel leaves the
        // user an empty box. Resolving through getInsertedComponentPanelVisibility rather than
        // reading the prop keeps this honest if the panel prop is renamed again.
        it.each([
            ['SQL', 'component-SQLV2'],
            ['Python', 'component-PythonV2'],
        ])('inserts a %s cell with its code editor open', (_label, commandKey) => {
            const insertedNodes: NotebookComponentBlockNode[] = []
            const noop = (): void => {}
            const commands = buildInsertCommands(
                mergeMarkdownNotebookRegistries(
                    getMarkdownNotebookDefaultRegistry(),
                    getMarkdownRegistryForFeatureFlags({ [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]: true })
                ),
                (_nodeId, node) => insertedNodes.push(node),
                noop,
                noop,
                noop,
                noop
            )

            commands.find((command) => command.key === commandKey)?.run('target-node')

            expect(insertedNodes).toHaveLength(1)
            expect(getInsertedComponentPanelVisibility(insertedNodes[0]).filters).toBe(true)
        })
    })

    describe('discussion comment composer', () => {
        const renderCommentShell = (componentPanels: ComponentPanelVisibility): ReturnType<typeof render> => {
            // No `showFilters` in props: composer visibility is driven by the transient panel
            // state, so the open state never has to be written into the shared document markdown.
            const node: NotebookComponentBlockNode = {
                id: 'comment-node',
                type: 'component',
                tagName: 'Comment',
                props: { replies: [] },
            }
            return render(
                <NotebookComponentShell
                    node={node}
                    mode="edit"
                    componentPanels={componentPanels}
                    persistComponentPanelVisibility={false}
                    isSelected={false}
                    registry={NOTEBOOK_MARKDOWN_REGISTRY}
                    toggleComponentPanel={jest.fn()}
                    setLocalComponentPanels={jest.fn()}
                    rememberComponentPanels={jest.fn()}
                    setBlockRef={jest.fn()}
                    updateNode={jest.fn()}
                    deleteNode={jest.fn()}
                    deleteSelectedNotebookBlocks={jest.fn(() => false)}
                    insertParagraphAfterNode={jest.fn()}
                    moveFocusToAdjacentNode={jest.fn(() => false)}
                />
            )
        }

        // The edit panel is what makes the composer editable, so a thread renders its composer
        // when that panel is open and the read-only view branch (no composer) when it is closed.
        // Insertion opens the panel transiently, so the composer never depends on a persisted prop.
        it.each([
            ['renders the composer when the edit panel is open', { filters: true, results: true }, true],
            ['renders no composer when the edit panel is closed', { filters: false, results: true }, false],
        ])('%s', (_label, componentPanels, expectComposer) => {
            const { container } = renderCommentShell(componentPanels)
            const composer = container.querySelector('[data-attr="notebook-discussion-comment-input"]')
            expect(composer !== null).toBe(expectComposer)
        })
    })

    describe('insert menu SQL commands', () => {
        // Exactly one SQL entry either way, and it stays in the menu's top group across the
        // flag flip so SQL doesn't move on people when the revamped cell takes over.
        it.each([
            [
                'the revamped SQL cell replaces the legacy one when the flag is on',
                true,
                [{ key: 'component-SQLV2', category: 'Common' }],
            ],
            [
                'the legacy SQL cell is the only one when the flag is off',
                false,
                [{ key: 'query-sql', category: 'Common' }],
            ],
        ])('%s', (_label, isFlagOn, expectedCommands) => {
            expect(getInsertCommandsByLabel({ [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]: isFlagOn }, 'SQL')).toEqual(
                expectedCommands
            )
        })
    })

    it('does not make real notebook nodes mutually exclusive in markdown notebooks', () => {
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.Recording.exclusiveEditPanel).toBeUndefined()
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.FeatureFlag.exclusiveEditPanel).toBeUndefined()
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.FeatureFlagCodeExample.exclusiveEditPanel).toBeUndefined()
    })

    it.each([
        'FeatureFlag',
        'FeatureFlagCodeExample',
        'Survey',
        'Experiment',
        'EarlyAccessFeature',
        'Cohort',
        'Insight',
        'Person',
        'Group',
        'Recording',
        'RecordingPlaylist',
        'ErrorTrackingIssue',
        'LLMTrace',
        'Dashboard',
        'Action',
        'Workflow',
    ])('uses the resource-derived title for %s nodes', (tagName) => {
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components[tagName].editableTitle).toBe(false)
    })

    it.each([
        ['FeatureFlag', NotebookNodeType.FeatureFlag],
        ['Survey', NotebookNodeType.Survey],
        ['Experiment', NotebookNodeType.Experiment],
        ['EarlyAccessFeature', NotebookNodeType.EarlyAccessFeature],
        ['Cohort', NotebookNodeType.Cohort],
        ['Insight', NotebookNodeType.Query],
        ['Recording', NotebookNodeType.Recording],
        ['RecordingPlaylist', NotebookNodeType.RecordingPlaylist],
        ['Person', NotebookNodeType.Person],
        ['Group', NotebookNodeType.Group],
        ['ErrorTrackingIssue', NotebookNodeType.ErrorTrackingIssue],
        ['LLMTrace', NotebookNodeType.LLMTrace],
        ['Dashboard', NotebookNodeType.Dashboard],
        ['Action', NotebookNodeType.Action],
        ['Workflow', NotebookNodeType.Workflow],
    ])('registers every catalog view for %s', (tagName, nodeType) => {
        const widget = notebookWidgetCatalog.widgets[tagName as keyof typeof notebookWidgetCatalog.widgets]
        const registeredViewNames = [
            KNOWN_NODES[nodeType].defaultView?.key,
            ...Object.keys(KNOWN_NODES[nodeType].views ?? {}),
        ]

        expect(registeredViewNames).toEqual([widget.defaultView.name, ...Object.keys(widget.views)])
    })

    it.each([
        {
            tagName: 'FeatureFlag',
            nodeType: NotebookNodeType.FeatureFlag,
            id: 123,
            idLabel: 'Feature flag ID or key',
            viewLabel: 'Editor',
            viewDescription: 'Edit the flag status and release conditions in the notebook.',
            viewKey: 'editor',
            viewKeys: ['summary', 'editor', 'conditions', 'implementation'],
        },
        {
            tagName: 'Survey',
            nodeType: NotebookNodeType.Survey,
            id: 'survey-id',
            idLabel: 'Survey ID',
            viewLabel: 'Preview',
            viewDescription: 'Show the first page of the survey.',
            viewKey: 'preview',
            viewKeys: ['summary', 'preview', 'conditions', 'results'],
        },
        {
            tagName: 'Experiment',
            nodeType: NotebookNodeType.Experiment,
            id: 456,
            idLabel: 'Experiment ID',
            viewLabel: 'Results',
            viewDescription: 'Show experiment exposures and primary metric results.',
            viewKey: 'results',
            viewKeys: ['summary', 'results'],
        },
        {
            tagName: 'EarlyAccessFeature',
            nodeType: NotebookNodeType.EarlyAccessFeature,
            id: 'feature-id',
            idLabel: 'Early access feature ID',
            viewLabel: 'Summary',
            viewDescription: 'Show the feature stage, name, and description.',
            viewKey: 'summary',
            viewKeys: ['summary'],
        },
        {
            tagName: 'Cohort',
            nodeType: NotebookNodeType.Cohort,
            id: 789,
            idLabel: 'Cohort ID',
            viewLabel: 'Summary',
            viewDescription: 'Show the cohort name, size, and type.',
            viewKey: 'summary',
            viewKeys: ['summary'],
        },
    ])(
        'edits the $tagName reference and selects a product-owned view',
        ({ tagName, nodeType, id, idLabel, viewLabel, viewDescription, viewKey, viewKeys }) => {
            const updateProps = jest.fn()
            const { container } = render(
                <RealNotebookNodeEdit
                    node={{
                        id: `${tagName}-node`,
                        type: 'component',
                        tagName,
                        props: { id },
                    }}
                    mode="edit"
                    updateProps={updateProps}
                    deleteNode={jest.fn()}
                />
            )
            const editor = within(container)
            const fields = Array.from(container.querySelectorAll('.MarkdownNotebook__component-form > label'))
            const idInput = editor.getByLabelText(idLabel) as HTMLInputElement
            const viewInput = editor.getByLabelText('View')

            expect(fields[0].contains(idInput)).toBe(true)
            expect(fields[1].contains(viewInput)).toBe(true)
            expect(idInput.value).toEqual(String(id))
            expect(viewInput.textContent).toContain('Detail')

            fireEvent.click(viewInput)
            expect(screen.getByLabelText(viewDescription).textContent).toContain(viewLabel)
            fireEvent.click(screen.getByLabelText(viewDescription))

            expect(updateProps).toHaveBeenCalledWith({ view: viewKey })
            expect(Object.keys(KNOWN_NODES[nodeType].views ?? {})).toEqual(viewKeys)
        }
    )

    it('keeps the resource ID before the view for nodes with product settings', () => {
        const { container } = render(
            <RealNotebookNodeIdentityAndViewEdit
                node={{
                    id: 'recording-node',
                    type: 'component',
                    tagName: 'Recording',
                    props: { id: 'recording-id' },
                }}
                mode="edit"
                updateProps={jest.fn()}
                deleteNode={jest.fn()}
                notebookNodeType={NotebookNodeType.Recording}
                options={KNOWN_NODES[NotebookNodeType.Recording]}
            />
        )
        const fields = Array.from(container.querySelectorAll('.MarkdownNotebook__component-form > label'))

        expect(fields[0].textContent).toContain('Session recording ID')
        expect(fields[1].textContent).toContain('View')
    })

    it('selects a referenced object from the same picker used by notebook insertion', () => {
        const updateProps = jest.fn()
        const { container } = render(
            <RealNotebookNodeEdit
                node={{
                    id: 'feature-flag-node',
                    type: 'component',
                    tagName: 'FeatureFlag',
                    props: { id: 123 },
                }}
                mode="edit"
                updateProps={updateProps}
                deleteNode={jest.fn()}
            />
        )
        const editor = within(container)

        fireEvent.click(editor.getByLabelText('Select feature flag id or key'))
        fireEvent.click(screen.getByLabelText('Pick from feature-flag'))

        expect(updateProps).toHaveBeenCalledWith({ id: 999 })
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
        expect(
            getEditableNodeAttributeKeys(KNOWN_NODES[NotebookNodeType.ZendeskTickets], {
                personId: undefined,
                groupKey: undefined,
            })
        ).toEqual(['personId', 'groupKey'])
    })

    it('uses product-specific labels for common reference attrs', () => {
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.FeatureFlag, 'id')).toEqual('Feature flag ID or key')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.Group, 'groupTypeIndex')).toEqual('Group type index')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.Person, 'distinctId')).toEqual('Distinct ID')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.ZendeskTickets, 'personId')).toEqual('Person UUID')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.ZendeskTickets, 'groupKey')).toEqual('Group key')
    })

    it('keeps numeric attrs numeric when edited through markdown filters', () => {
        expect(getSerializableAttributeInputValue(NotebookNodeType.Cohort, 'id', '123')).toEqual(123)
        expect(getSerializableAttributeInputValue(NotebookNodeType.Group, 'groupTypeIndex', '2')).toEqual(2)
        expect(getSerializableAttributeInputValue(NotebookNodeType.FeatureFlag, 'id', 'flag-key')).toEqual('flag-key')
        expect(getSerializableAttributeInputValue(NotebookNodeType.FeatureFlag, 'id', ' flag-key ')).toEqual('flag-key')
        expect(getSerializableAttributeInputValue(NotebookNodeType.Group, 'groupTypeIndex', ' not-a-number ')).toEqual(
            'not-a-number'
        )
    })

    it('renders a SQL cell whose query arrived as a query prop', () => {
        // Regression: a `<SQLV2 query={…} />` cell (the shape AI-authored notebooks use) has no
        // `code` prop, so the editor rendered blank with no way to see or run the query.
        const attributes = getNodeAttributes(
            {
                query: {
                    kind: 'DataVisualizationNode',
                    source: { kind: 'HogQLQuery', query: 'select event from events' },
                    display: 'ActionsBar',
                },
            },
            'block-1',
            KNOWN_NODES[NotebookNodeType.SQLV2],
            NotebookNodeType.SQLV2,
            false
        )

        expect(attributes.code).toEqual('select event from events')
        expect(attributes.vizQuery).toMatchObject({ display: 'ActionsBar' })
    })

    describe('getQueryTitle', () => {
        it.each([
            [
                'ActorsQuery resolves to People, not the schema kind',
                { kind: 'DataTableNode', source: { kind: 'ActorsQuery' } },
                'People',
            ],
            ['EventsQuery resolves to Events', { kind: 'DataTableNode', source: { kind: 'EventsQuery' } }, 'Events'],
            [
                'HogQLQuery stays untitled — no SQL body, no generic label',
                { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'select event from events' } },
                null,
            ],
            ['an unrecognized query suggests no title rather than the raw kind', { kind: 'DataTableNode' }, null],
        ])('%s', (_label, query, expected) => {
            expect(getQueryTitle(query)).toEqual(expected)
        })
    })
})

import { IconCopy, IconSparkles, IconTrash } from '@posthog/icons'
import { Button, Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { BlockPropsRecord, blockDefinition } from '../../../editing/blockLibrary/blockDefinitions'
import { SQL_BLOCK_TYPES } from '../../../editing/blockLibrary/blockSql'
import type { CanvasEditSelection } from '../../../editing/canvasSourceSnapshots'
import { CommonBlockFields } from './CommonBlockFields'
import { ComponentFields } from './ComponentFields'
import { ControlNote } from './ControlNote'
import { DraftTextarea } from './DraftTextarea'
import { InspectorField } from './InspectorField'
import { BlockPropsChange, editableProps } from './inspectorValues'
import { ParamField } from './ParamField'
import { QueryModeFields } from './QueryModeFields'

function BlockFields({
    selection,
    props,
    onChange,
}: {
    selection: CanvasEditSelection
    props: BlockPropsRecord
    onChange: BlockPropsChange
}): JSX.Element | null {
    if (selection.params) {
        return (
            <>
                {selection.params.map(({ name, spec }) => (
                    <ParamField
                        key={name}
                        name={name}
                        spec={spec}
                        value={props[name] ?? spec.fallback}
                        onChange={(value) => onChange({ ...props, [name]: value })}
                    />
                ))}
            </>
        )
    }
    if (!selection.blockType) {
        return null
    }
    return <ComponentFields type={selection.blockType} props={props} onChange={onChange} />
}

/** The settings of the selected block or element, and the actions on it. */
export function CanvasSourceInspector({
    selection,
    isRoot,
    onProps,
    onText,
    onDuplicate,
    onRemove,
}: {
    selection: CanvasEditSelection
    isRoot: boolean
    onProps: (props: BlockPropsRecord) => void
    onText: (text: string) => void
    onDuplicate: () => void
    onRemove: () => void
}): JSX.Element {
    const props = editableProps(selection.props)
    return (
        <div className="flex flex-col gap-4 p-3">
            {selection.params && selection.blockType && !blockDefinition(selection.blockType) ? (
                <Item variant="muted" size="xs" className="items-start">
                    <ItemMedia variant="icon" aria-hidden>
                        <IconSparkles />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>Set up by the agent</ItemTitle>
                        <ItemDescription>
                            These fields come from the component's code, so you can change them without a prompt.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : null}
            {selection.blockType && SQL_BLOCK_TYPES.has(selection.blockType) ? (
                <QueryModeFields type={selection.blockType} props={props} onChange={onProps}>
                    <BlockFields selection={selection} props={props} onChange={onProps} />
                </QueryModeFields>
            ) : (
                <BlockFields selection={selection} props={props} onChange={onProps} />
            )}
            <CommonBlockFields selection={selection} props={props} onChange={onProps} />
            {!selection.blockType && selection.text !== null ? (
                <InspectorField label="Text">
                    <DraftTextarea value={selection.text} ariaLabel="Text" rows={3} onCommit={onText} />
                </InspectorField>
            ) : null}
            {!selection.blockType && selection.text === null ? (
                <ControlNote>
                    {isRoot
                        ? 'This is the whole canvas. Drag blocks into it from the panel.'
                        : 'Move this element by dragging it on the canvas, or ask the agent to change it.'}
                </ControlNote>
            ) : null}
            {isRoot ? null : (
                <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" onClick={onDuplicate} data-attr="canvas-block-duplicate">
                        <IconCopy />
                        Duplicate
                    </Button>
                    <Button variant="outline" size="sm" onClick={onRemove} data-attr="canvas-block-delete">
                        <IconTrash />
                        Delete
                    </Button>
                </div>
            )}
        </div>
    )
}

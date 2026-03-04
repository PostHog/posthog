# Survey Forms

Forms are a new variant of "hosted" surveys. They use surveys plumbing under the hood for the response pipeline, but have their own types, editing UI, and end-user interface.

## TL;DR - how it works

_most important bits here, continue reading for more!_

**`surveys.form_content` is the source of truth for Form data.**

- `survey.questions` is **only a projection** derived on save
- We do this because forms need richer question types, but we want to leverage the existing survey response pipeline

**Form content is TipTap-style JSON content with custom nodes.**

- Users build forms in a Notion-style document editor
- Custom nodes include question types, page breaks, etc
- On save, survey questions are extracted, converted, and projected to `survey.questions`
- Forms have more/richer question types than surveys, but each maps to a survey question type, sometimes with additional metadata

## Quick code pointers

- Builder entrypoint: [`SurveyFormBuilder.tsx`](./SurveyFormBuilder.tsx)
- Core logic: [`surveyFormBuilderLogic.ts`](./surveyFormBuilderLogic.ts)
- TipTap editor: [`FormEditor.tsx`](./components/editor/FormEditor.tsx)

## Glossary

- **Document:** the TipTap document, stored as `survey.form_content.content`, the source of truth for Form data
- **Page break:** a "normal" page break node.
- **Thank-you page break:** explicitly refers to a special type of page break for the survey "thank you" page

# Form flow

## Pages

Forms may have any number of questions per page.

**Page break nodes** represent the start of a new page. They are real nodes within the TipTap document, and therefore can be configured/moved/deleted by users.

There are two types of page break nodes:

### Normal page break

_("page break" always refers to a normal page break, unless explicitly specified)_

ref: [`FormPageBreakNode.tsx`](./components/editor/nodes/FormPageBreakNode.tsx)

Normal page breaks start a new page for the form. This enables users to have any number of questions per page.

### Thank-you page break

_(always explicitly referred to as a "thank-you page break")_

ref: [`FormThankYouBreakNode.tsx`](./components/editor/nodes/FormThankYouBreakNode.tsx)

Thank-you page breaks signal the end of the form, and the start of custom content for the form's "thank-you" / "confirmation" page.

If a thank-you page break is not present, we render a generic thank-you message at the end of the form.

These nodes store no additional metadata, and there may be only one thank-you page break per form.

## Next/Submit Buttons

ref: [`FormButtonNode.tsx`](./components/editor/nodes/FormButtonNode.tsx)

There are two types of buttons: `next` and `submit`. The form builder automatically inserts these buttons where needed. Users can only edit their text/styling.

**Submit button:** signals the end of the form. Added at the very end of the form, or above the thank-you page break if it exists.

**Next buttons:** signals the end of a page. Added above each page break node. If there are no page break nodes (excluding thank-you page breaks), there will be no next buttons, only a submit button.

# Contributing

## Adding new question types

Form question types all map directly to normal survey types, sometimes with additional metadata. For example, the form question types `ShortText` and `LongText` both map to `SurveyQuestionType.Open`, but the form UI renders `LongText` with a larger text area.

An example, adding a new file upload question type:

### Step 1: Define the type

In [`formTypes.ts`](./formTypes.ts):

```typescript
// 1) add to enum
export enum FormQuestionType {
    ...
    FileUpload = 'file_upload',
}

// 2) define interface, extending base
export interface FormFileUploadQuestion extends FormQuestionBase {
    type: FormQuestionType.FormQuestionType
    // example additional metadata:
    allowedFileTypes: string[]
}

// 3) update the FormQuestion type
export type FormQuestion =
    ...
    | FormFileUploadQuestion
```

### Step 2: Write survey question adapter logic

Build an adapter in [`toSurveyQuestion`](./components/questions/formQuestionAdapter.ts) to convert the new question type to a `SurveyQuestion`.

```typescript
case FormQuestionType.FileUpload:
    return { ...base, type: SurveyQuestionType.Open }
```

**_Note that not all form data needs to be in the survey question_.**

In this example `allowedFileTypes` are not in the core survey data, and that's ok. The end-user UI reads the form data as the source of truth.

### Step 3: Build a preview node

Build a preview node in [`previews`](./components/questions/previews).

This will be rendered in the form editor, and should contain the preview & any user-configurable options specific to your question type.

```typescript
/**
 * Props passed to all preview nodes:
 * - question: FormQuestion (cast it to your new type)
 * - onUpdate: (q: FormQuestion) => void
 */
export function MyNewQuestionTypePreview({ question, onUpdate }: QuestionPreviewProps): JSX.Element {
    // cast question to your type
    const q = question as FormFileUploadQuestion

    // type-specific update handler logic
    const handleChange = useCallback((values: string[]): void => {
        onUpdate({ ...q, allowedFileTypes: values })
    }, [q, onUpdate])

    return (
        <div className="mt-2">
            {/* preview */}
            <div className="w-full flex flex-col items-center justify-center rounded-md border border-border bg-bg-3000 px-3 py-2 text-muted text-sm">
                <div className="flex gap-2 items-center justify-center">
                    <UploadIcon /> Upload your file
                </div>
                {/* can (should) by dynamic! */}
                <span className="text-muted">Allowed types: {q.allowedFileTypes.join(', ')}</span>
            </div>

            {/* user-editable list of allowed filetypes */}
            <LemonInputSelect
                mode="multiple"
                options={FILE_TYPE_OPTIONS}
                value={q.allowedFileTypes}
                onChange={handleChange}
                placeholder="Add allowed file types..."
                fullWidth
                size="small"
                formatCreateLabel={(input) => `Add "${input}"`}
            />
        </div>
    )
}
```

### Step 4 (optional): Declare settings

If your question type has configurable options (e.g. a scale selector), declare them in the registry entry's `settings` field.

See **Form question settings** below.

### Done!

Your new form question type will now be accessible from the plus button / slash command menus and get stored properly in both `survey.form_content` and `survey.questions`.

## Form question settings

Settings are declared in the form question type registry. The drag handle menu dynamically renders UI components for each setting.

Each question gets a "Required" boolean setting by default. Currently, you can add new settings with types `select`, `toggle`, or `input`. `toggle`-type settings may also have `children`, which will render when the toggle is **on**.

Example scale setting emoji rating questions:

```typescript
settings: (question) => {
    const q = question as FormEmojiRatingQuestion
    return [
        {
            type: SettingType.Select,
            label: 'Scale',
            value: q.scale,
            apply: (v: string | number) => ({ ...q, scale: v }) as FormQuestion,
            options: [
                { label: '1-2', value: 2 },
                { label: '1-3', value: 3 },
                { label: '1-5', value: 5 },
            ],
        },
    ]
},
```

### Conditional settings

For toggle settings, include `children` which will render when the toggle is **on**. Example:

```typescript
settings: (question) => {
    const q = question as FormEmojiRatingQuestion
    return [
        {
            type: SettingType.Toggle,
            label: 'Validate length',
            checked: q.validateLength,
            apply: (v: boolean) => ({ ...q, validateLength: v }) as FormQuestion,
            children: [
                {
                    type: SettingType.Input,
                    label: 'Min characters',
                    value: q.minCharacters,
                    inputType: 'number',
                    apply: (v: string | number) => ({ ...q, minCharacters: v }) as FormQuestion,
                },
                {
                    type: SettingType.Input,
                    label: 'Max characters',
                    value: q.maxCharacters,
                    inputType: 'number',
                    apply: (v: string | number) => ({ ...q, maxCharacters: v }) as FormQuestion,
                },
            ]
        },
    ]
},
```

For non-toggle settings, you can access any data about the current question to return the appropriate settings.

Example for `isNpsQuestion` on number scales:

```typescript
settings: (question) => {
    const q = question as FormNumberScaleQuestion
    let options: QuestionTypeSetting[] = [
        {
            type: SettingType.Select,
            label: 'Scale',
            value: q.scale,
            apply: (v: string | number) => {
                const newScale = parseInt(v.toString())
                const newQuestion: FormNumberScaleQuestion = {
                    ...q,
                    scale: newScale,
                    isNpsQuestion: newScale === 10,
                }
                return newQuestion
            },
            options: [
                { label: '1-5', value: 5 },
                { label: '1-7', value: 7 },
                { label: '1-10', value: 10 },
            ],
        },
    ]
    if (q.scale === 10) {
        options.push({
            type: SettingType.Toggle,
            label: 'NPS Question',
            checked: q.isNpsQuestion,
            apply: (v: boolean) => ({ ...q, isNpsQuestion: v }) as FormQuestion,
        })
    }
    return options
},
```

### Add a new setting type

1. In [`formTypes.ts`](./formTypes.ts), add new setting type to `SettingType` enum
2. In [`formTypes.ts`](./formTypes.ts), build the interface for your setting, then add it to `QuestionTypeSetting`
3. Update `settingToMenuItem` in [`FormDragHandle.tsx`](./components/editor/FormDragHandle.tsx) to handle your new setting type

## Document structure

The document is defined with a required structure that ensures it starts with a heading, so we can reliably extract the form's title:

```typescript
const FormDocument = ExtensionDocument.extend({
  content: 'heading block*',
})
```

We also have a custom `TitleGuard` extension that guards against users dragging content above it.

## Non-document customization

Some options do not live within the document, such as a custom logo or cover image.

These options exist in the custom `TitleActions` extension, which adds floating buttons (e.g. "Add logo") above the title.

## Page break & button logic

### Page breaks

ref: [`computePageNumber`](./components/editor/nodes/FormPageBreakNode.tsx)

Page break nodes are pretty simple. We just compute their page numbers dynamically on each change to the editor. Each page break nodes gets an ID so we can reconcile custom button text if the document shape changes.

### Buttons

Buttons are more complicated. They are **not user-insertable** - they are automatically added by a ProseMirror plugin on every document change.

Users can only edit the button text; they cannot add/delete/drag them.

The plugin runs [`buildDesiredTopLevelNodes`](./components/editor/nodes/FormButtonNode.tsx) on every change to the document:

1. Strips all existing button nodes, storing their metadata (custom text) in case it needs to be re-added
2. Inserts a **next button** directly above each page break node, linked to the page break node's ID
3. If the document has real content, inserts a **submit button** either:
   - Above the thank-you page break node, if one exists
   - At the very end of the document, otherwise
4. Compares the desired node list to the current document; if they differ, replaces the entire document using `addToHistory: false` to prevent undos

User-edited button text is preserved across rewrites by reading existing button text before stripping the document, and referencing the target page break node's ID.

_Note: yes, this could use some work, and does cause problems with things that require cursor tracking (like auto-focus) since the entire document gets replaced_

## Drag handle & drag-n-drop

Real talk: _this is a bit of a mess_, but it works, and it's pretty smooth.

There are two pieces: the **drag handle** (React component) and the **drag feedback** (ProseMirror plugin).

### Drag handle

ref: [`FormDragHandle.tsx`](./components/editor/FormDragHandle.tsx)

The drag handle is a React component that uses TipTap's `DragHandle` extension. It renders two buttons next to whichever node the user is hovering over: a **plus button** (insert menu) and a **grip button** (context menu + drag initiator).

The handle is hidden for the title node and button nodes.

A few things that are annoying but necessary:

- **Menu pinning:** when a menu opens, we `position: fixed` the handle to its current screen position and lock the drag handle. Otherwise TipTap's `onNodeChange` fires as the cursor moves and the handle jumps around while you're trying to click a menu item.
- **Drag guard:** during a drag, we set a `draggingRef` and ignore `onNodeChange` callbacks until two `requestAnimationFrame` ticks after drop. This lets the post-drop ProseMirror transaction and React re-render settle before the handle starts tracking again.
- **Context menu:** for question nodes, the grip menu includes type-specific settings declared in the registry's `settings` field. These are built dynamically from the node's `questionData` attrs and write back via `setNodeMarkup`.

### Drag feedback

ref: [`FormDragFeedback.ts`](./components/editor/FormDragFeedback.ts)

This is a ProseMirror plugin that handles the visual feedback during drag-n-drop. ProseMirror's built-in drop behavior doesn't give us enough control, so we override it entirely.

The plugin tracks four pieces of state: `isDragging`, `draggedPos`, `slotPos`, and `slotGapIndex`.

On `dragstart`, it records the dragged node's position and adds a `dragging` CSS class to the editor.

On `dragover`, it:

1. Finds all top-level blocks (excluding widgets and button nodes)
2. Finds the nearest "gap" between blocks based on mouse Y position
3. Skips the gap if it's a no-op (dropping a node right where it already is)
4. Prevents dropping above the title (gap index 0 is always bumped to 1)
5. Has "sticky" gap behavior — once a drop slot is shown, it stays until the cursor moves to a different gap. This prevents the slot from flickering when the cursor is near a gap boundary.

The plugin renders two decorations:

- A `form-dragging-source` node decoration on the node being dragged (dims it)
- A `form-drop-slot-widget` widget decoration at the drop position (the "Drop here" indicator)

On `handleDrop`, the plugin does the actual move: delete the node from its original position, map the drop position through the deletion, insert the node at the mapped position. This is done in a single transaction so it's a single undo step.

## Trailing nodes

To make editing a bit smoother, we append **trailing nodes** when certain nodes are inserted.

For example, when a user adds a new question node, we insert an empty paragraph below it.

```typescript
// ex: FormQuestionNode:addCommands
return commands.insertContent([
  // insert the desired node
  {
    type: this.name,
    attrs: {
      questionId: attrs.questionId,
      questionData: JSON.stringify(attrs.question),
      focusOnMount: true,
    },
  },
  // insert a trailing node
  { type: 'paragraph' },
])
```

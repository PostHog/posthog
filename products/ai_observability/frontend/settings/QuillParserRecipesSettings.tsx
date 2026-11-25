import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldGroup,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemGroup,
    ItemTitle,
    Skeleton,
    Text,
    Textarea,
} from '@posthog/quill'

import { CustomRecipeItem, parserRecipesLogic } from './parserRecipesLogic'
import { confirmDeleteRecipe, recipeSaveDisabledReason } from './ParserRecipesSettings'

function QuillRecipeRow({ item }: { item: CustomRecipeItem }): JSX.Element {
    const { openEditorForItem, deleteItem } = useActions(parserRecipesLogic)

    return (
        <Item variant="outline" size="sm">
            <ItemContent className="min-w-0">
                <ItemTitle className="ph-no-capture truncate">{item.name}</ItemTitle>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={() => openEditorForItem(item)}>
                    Edit
                </Button>
                <Button variant="destructive-outline" onClick={() => confirmDeleteRecipe(item, deleteItem)}>
                    Delete
                </Button>
            </ItemActions>
        </Item>
    )
}

function QuillRecipeEditorDialog(): JSX.Element {
    const { editor, savingEditor, editorCompileError } = useValues(parserRecipesLogic)
    const { closeEditor, setEditorName, setEditorSource, submitEditor } = useActions(parserRecipesLogic)

    return (
        <Dialog open={!!editor} onOpenChange={(open: boolean) => !open && closeEditor()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>{editor?.rowId ? 'Edit recipe' : 'New recipe'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    {editor && (
                        <FieldGroup>
                            <Field>
                                <Input
                                    placeholder="Recipe name"
                                    aria-label="Recipe name"
                                    value={editor.name}
                                    onChange={(event) => setEditorName(event.target.value)}
                                />
                            </Field>
                            <Field data-invalid={!!editorCompileError || undefined}>
                                <Textarea
                                    className="font-mono min-h-60"
                                    value={editor.source}
                                    onChange={(event) => setEditorSource(event.target.value)}
                                    placeholder="Recipe YAML"
                                    aria-label="Recipe YAML"
                                    aria-invalid={!!editorCompileError || undefined}
                                />
                                {editorCompileError && <FieldError>{editorCompileError}</FieldError>}
                            </Field>
                        </FieldGroup>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeEditor}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={submitEditor}
                        loading={savingEditor}
                        disabledReason={recipeSaveDisabledReason(editor, editorCompileError)}
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

export function QuillParserRecipesSettings(): JSX.Element {
    const { customItems, storedRecipesLoading } = useValues(parserRecipesLogic)
    const { openEditorForNew } = useActions(parserRecipesLogic)

    if (storedRecipesLoading) {
        return <Skeleton className="h-10 w-full" />
    }

    return (
        <div className="flex flex-col gap-2">
            {customItems.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No custom recipes yet. Add one to normalize a provider shape the built-in recipes miss.
                </Text>
            ) : (
                <ItemGroup className="gap-1">
                    {customItems.map((item) => (
                        <QuillRecipeRow key={item.id} item={item} />
                    ))}
                </ItemGroup>
            )}
            <div>
                <Button variant="primary" onClick={openEditorForNew}>
                    Add recipe
                </Button>
            </div>
            <QuillRecipeEditorDialog />
        </div>
    )
}

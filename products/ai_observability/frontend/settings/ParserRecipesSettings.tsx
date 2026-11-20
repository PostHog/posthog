import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { CustomRecipeItem, RecipeEditorState, parserRecipesLogic } from './parserRecipesLogic'
import { QuillParserRecipesSettings } from './QuillParserRecipesSettings'

export function confirmDeleteRecipe(item: CustomRecipeItem, deleteItem: (item: CustomRecipeItem) => void): void {
    LemonDialog.open({
        title: 'Delete recipe?',
        description: `This permanently deletes "${item.name}". This cannot be undone.`,
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            onClick: () => deleteItem(item),
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function recipeSaveDisabledReason(
    editor: RecipeEditorState | null,
    editorCompileError: string | null
): string | undefined {
    return !editor?.name.trim()
        ? 'Recipe name is required'
        : editorCompileError
          ? 'Recipe YAML does not compile'
          : undefined
}

export function ParserRecipesSettings(): JSX.Element {
    const { customItems, storedRecipesLoading } = useValues(parserRecipesLogic)
    const { openEditorForNew } = useActions(parserRecipesLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillParserRecipesSettings />
    }

    if (storedRecipesLoading) {
        return <Spinner />
    }

    return (
        <div className="flex flex-col gap-2">
            {customItems.length === 0 ? (
                <p className="text-muted">
                    No custom recipes yet. Add one to normalize a provider shape the built-in recipes miss.
                </p>
            ) : (
                <div className="flex flex-col gap-1">
                    {customItems.map((item) => (
                        <RecipeRow key={item.id} item={item} />
                    ))}
                </div>
            )}
            <div>
                <LemonButton type="primary" onClick={openEditorForNew}>
                    Add recipe
                </LemonButton>
            </div>
            <RecipeEditorModal />
        </div>
    )
}

function RecipeRow({ item }: { item: CustomRecipeItem }): JSX.Element {
    const { openEditorForItem, deleteItem } = useActions(parserRecipesLogic)

    return (
        <div className="flex items-center gap-2 border rounded p-2 bg-bg-light">
            <span className="font-medium flex-1 ph-no-capture">{item.name}</span>
            <LemonButton size="small" type="secondary" onClick={() => openEditorForItem(item)}>
                Edit
            </LemonButton>
            <LemonButton
                size="small"
                type="secondary"
                status="danger"
                onClick={() => confirmDeleteRecipe(item, deleteItem)}
            >
                Delete
            </LemonButton>
        </div>
    )
}

function RecipeEditorModal(): JSX.Element {
    const { editor, savingEditor, editorCompileError } = useValues(parserRecipesLogic)
    const { closeEditor, setEditorName, setEditorSource, submitEditor } = useActions(parserRecipesLogic)

    return (
        <LemonModal
            isOpen={!!editor}
            onClose={closeEditor}
            title={editor?.rowId ? 'Edit recipe' : 'New recipe'}
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeEditor}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitEditor}
                        loading={savingEditor}
                        disabledReason={recipeSaveDisabledReason(editor, editorCompileError)}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            {editor && (
                <div className="flex flex-col gap-2 w-full">
                    <LemonInput placeholder="Recipe name" value={editor.name} onChange={setEditorName} />
                    <LemonTextArea
                        className="font-mono"
                        value={editor.source}
                        onChange={setEditorSource}
                        minRows={12}
                        placeholder="Recipe YAML"
                    />
                    {editorCompileError && <p className="text-danger text-sm m-0">{editorCompileError}</p>}
                </div>
            )}
        </LemonModal>
    )
}

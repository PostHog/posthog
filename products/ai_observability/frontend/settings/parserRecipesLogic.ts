import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import { parse as parseYaml } from 'yaml'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    llmAnalyticsParserRecipesCreate,
    llmAnalyticsParserRecipesDestroy,
    llmAnalyticsParserRecipesList,
    llmAnalyticsParserRecipesPartialUpdate,
} from '../generated/api'
import { ParserRecipeApi } from '../generated/api.schemas'
import { applyTeamParserRecipes } from '../messageNormalization'
import { compileRecipe, StoredRecipe } from '../normalizer'
import type { parserRecipesLogicType } from './parserRecipesLogicType'

export interface CustomRecipeItem {
    id: string
    name: string
    source: string
}

export interface RecipeEditorState {
    rowId: string | null
    name: string
    source: string
}

const NEW_CUSTOM_SOURCE = 'rules:\n    - on:\n          $: { exists: true }\n      emit:\n          content: $\n'

export function sourceCompileError(source: string): string | null {
    try {
        // The id is supplied from the database at merge time, so a missing one is fine here.
        compileRecipe(parseYaml(source), 'preview')
        return null
    } catch (err) {
        return err instanceof Error ? err.message : String(err)
    }
}

// Owns the team's custom recipes end to end: loads them, pushes them into the live
// trace-rendering normalizer, and backs the settings editor. Mounted on every AI
// observability view via aiObservabilitySharedLogic so customizations apply even when
// the settings scene was never opened; the editor parts stay dormant outside settings.
export const parserRecipesLogic = kea<parserRecipesLogicType>([
    path(['products', 'ai_observability', 'frontend', 'settings', 'parserRecipesLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        openEditorForNew: true,
        openEditorForItem: (item: CustomRecipeItem) => ({ item }),
        closeEditor: true,
        setEditorName: (name: string) => ({ name }),
        setEditorSource: (source: string) => ({ source }),
        submitEditor: true,
        submitEditorDone: true,
        deleteItem: (item: CustomRecipeItem) => ({ item }),
        recipesApplied: true,
    }),
    loaders(({ values }) => ({
        storedRecipes: [
            [] as ParserRecipeApi[],
            {
                loadRecipes: async () => {
                    return (await llmAnalyticsParserRecipesList(String(values.currentTeamId), { limit: 1000 })).results
                },
            },
        ],
    })),
    reducers({
        editor: [
            null as RecipeEditorState | null,
            {
                closeEditor: () => null,
                openEditorForNew: () => ({ rowId: null, name: '', source: NEW_CUSTOM_SOURCE }),
                openEditorForItem: (_, { item }) => ({ rowId: item.id, name: item.name, source: item.source }),
                setEditorName: (state, { name }) => (state ? { ...state, name } : state),
                setEditorSource: (state, { source }) => (state ? { ...state, source } : state),
            },
        ],
        savingEditor: [
            false,
            {
                submitEditor: () => true,
                submitEditorDone: () => false,
                closeEditor: () => false,
            },
        ],
        // The normalizer is a module singleton; memoized normalizations include this in their
        // deps to re-render when the recipe set changes
        recipesVersion: [
            0,
            {
                recipesApplied: (state) => state + 1,
            },
        ],
    }),
    selectors({
        storedForMerge: [
            (s) => [s.storedRecipes],
            (rows): StoredRecipe[] => rows.map((row) => ({ id: row.id, source: row.source })),
        ],
        customItems: [
            (s) => [s.storedRecipes],
            (rows: ParserRecipeApi[]): CustomRecipeItem[] =>
                rows.map((row) => ({ id: row.id, name: row.name, source: row.source })),
        ],
        editorCompileError: [
            (s) => [s.editor],
            (editor): string | null => (editor ? sourceCompileError(editor.source) : null),
        ],
    }),
    subscriptions(({ actions }) => ({
        // Fires on mount with the initial value, then on every change — so this covers
        // the first load and project switches.
        currentTeamId: (currentTeamId: number | null) => {
            if (currentTeamId !== null) {
                actions.loadRecipes()
            }
        },
    })),
    listeners(({ actions, values }) => ({
        loadRecipesSuccess: () => {
            applyTeamParserRecipes(values.storedForMerge)
            actions.recipesApplied()
        },
        submitEditor: async () => {
            const editor = values.editor
            if (!editor) {
                return
            }
            const name = editor.name.trim()
            if (!name) {
                lemonToast.error('Recipe name is required')
                actions.submitEditorDone()
                return
            }
            if (values.editorCompileError) {
                lemonToast.error(`Recipe does not compile: ${values.editorCompileError}`)
                actions.submitEditorDone()
                return
            }
            try {
                if (editor.rowId) {
                    await llmAnalyticsParserRecipesPartialUpdate(String(values.currentTeamId), editor.rowId, {
                        name,
                        source: editor.source,
                    })
                } else {
                    await llmAnalyticsParserRecipesCreate(String(values.currentTeamId), { name, source: editor.source })
                }
                actions.loadRecipes()
                actions.closeEditor()
                lemonToast.success('Recipe saved')
            } catch {
                lemonToast.error('Could not save recipe')
                actions.submitEditorDone()
            }
        },
        deleteItem: async ({ item }) => {
            try {
                await llmAnalyticsParserRecipesDestroy(String(values.currentTeamId), item.id)
                actions.loadRecipes()
                lemonToast.success('Recipe deleted')
            } catch {
                lemonToast.error('Could not delete recipe')
            }
        },
    })),
])

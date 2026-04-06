// Remembers which survey editor (guided wizard vs full editor) the user last
// chose, via localStorage. Used on "new survey" landing pages to redirect
// users straight to their preferred editor without an extra click.

const STORAGE_KEY = 'posthog.surveys.preferredEditor'

export type SurveyEditorPreference = 'guided' | 'full'

export const getPreferredSurveyEditor = (): SurveyEditorPreference => {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'full' ? 'full' : 'guided'
}

export const setPreferredSurveyEditor = (editor: SurveyEditorPreference): void => {
    localStorage.setItem(STORAGE_KEY, editor)
}

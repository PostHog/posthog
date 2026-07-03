import { Monaco } from '@monaco-editor/react'
import { languages } from 'monaco-editor'

export const conf: () => languages.LanguageConfiguration = () => ({
    comments: {
        lineComment: '#',
    },
})

export const language: () => languages.IMonarchLanguage = () => ({
    defaultToken: '',
    tokenizer: {
        root: [
            [/#.*$/, 'comment'],
            // Email owners — matched before the path rule, which stops at '@'.
            [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, 'type'],
            // Team / user owners: @org/team, @user.
            [/@[A-Za-z0-9/_.-]+/, 'type'],
            // Path patterns, including glob wildcards.
            [/[^\s#@]+/, 'string'],
        ],
    },
})

export function initCodeownersLanguage(monaco: Monaco): void {
    if (!monaco.languages.getLanguages().some((lang: { id: string }) => lang.id === 'codeowners')) {
        monaco.languages.register({ id: 'codeowners' })
        monaco.languages.setLanguageConfiguration('codeowners', conf())
        monaco.languages.setMonarchTokensProvider('codeowners', language())
    }
}

import { Monaco } from '@monaco-editor/react'

import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'

import { HogLanguage } from '~/queries/schema/schema-general'

import { MonacoDisposable } from '../CodeEditor'

export function initLiquidLanguage(monaco: Monaco): MonacoDisposable[] {
    const disposables: MonacoDisposable[] = []

    // Liquid is a pre-registered language in Monaco, so we expand its configuration here
    // instead of registering anything like we do for our custom languages.
    const languageConfiguration = monaco.languages.getLanguages().find((lang) => lang.id === 'liquid')
    if (languageConfiguration && !languageConfiguration.extensions) {
        disposables.push(
            monaco.languages.registerCompletionItemProvider('liquid', hogQLAutocompleteProvider(HogLanguage.liquid))
        )
        disposables.push(monaco.languages.registerCodeActionProvider('liquid', hogQLMetadataProvider()))
    }

    return disposables
}

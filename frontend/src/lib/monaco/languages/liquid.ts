import { Monaco } from '@monaco-editor/react'

import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'

import { HogLanguage } from '~/queries/schema/schema-general'

import { MonacoDisposable } from '../CodeEditor'

export function initLiquidLanguage(monaco: Monaco): MonacoDisposable[] {
    const disposables: MonacoDisposable[] = []

    /**
     * Hack: Multiple Monaco instances can render at the same time, so we need a way to determine
     * if the completion provider has already been registered. Monaco does not expose the registered providers for
     * languages, so we'll do so with a noop hogLiquid language registration as a flag like we do with other languages
     * in this directory
     */
    if (!monaco.languages.getLanguages().some((lang) => lang.id === 'hogLiquid')) {
        monaco.languages.register({ id: 'hogLiquid' })
        // Liquid is a pre-registered language in Monaco, so we only need to register completion and code action providers.
        disposables.push(
            monaco.languages.registerCompletionItemProvider('liquid', hogQLAutocompleteProvider(HogLanguage.liquid))
        )
        disposables.push(monaco.languages.registerCodeActionProvider('liquid', hogQLMetadataProvider()))
    }

    return disposables
}

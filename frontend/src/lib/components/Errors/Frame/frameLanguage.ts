import { Language, getLanguage } from 'lib/components/CodeSnippet'

import type { ErrorTrackingStackFrame } from '../types'

const SOURCE_LANGUAGE_OVERRIDES: Record<string, Language> = {
    cs: Language.CSharp,
    cts: Language.TypeScript,
    dart: Language.Dart,
    groovy: Language.Groovy,
    kt: Language.Kotlin,
    kts: Language.Kotlin,
    mts: Language.TypeScript,
    ts: Language.TypeScript,
    tsx: Language.TypeScript,
    vb: Language.VBNet,
}

export function getFrameLanguage({ lang, source }: Pick<ErrorTrackingStackFrame, 'lang' | 'source'>): Language {
    const sourceExtension = source?.match(/\.([^./?#]+)(?:[?#].*)?$/)?.[1]?.toLowerCase()
    return (sourceExtension && SOURCE_LANGUAGE_OVERRIDES[sourceExtension]) || getLanguage(lang)
}

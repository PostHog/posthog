import { Language } from 'lib/components/CodeSnippet'

import { getFrameLanguage } from './frameLanguage'

describe('getFrameLanguage', () => {
    it.each([
        ['TypeScript', 'javascript', 'src/lib/api.ts', Language.TypeScript],
        ['TSX', 'javascript', 'src/components/App.tsx', Language.TypeScript],
        ['ES module TypeScript', 'javascript', 'src/server.mts', Language.TypeScript],
        ['CommonJS TypeScript', 'javascript', 'src/server.cts', Language.TypeScript],
        ['Dart compiled for web', 'javascript', 'src/main.dart', Language.Dart],
        ['Kotlin on the JVM', 'java', 'Checkout.kt', Language.Kotlin],
        ['Groovy on the JVM', 'java', 'Checkout.groovy', Language.Groovy],
        ['C# on .NET', 'dotnet', 'Checkout.cs', Language.CSharp],
        ['Visual Basic on .NET', 'dotnet', 'Checkout.vb', Language.VBNet],
        ['Objective-C++', 'objectivecpp', 'Checkout.mm', Language.ObjectiveC],
        ['Luau', 'luau', 'ServerScriptService.Checkout', Language.Lua],
    ])('uses %s highlighting for source context', (_label, lang, source, expected) => {
        expect(getFrameLanguage({ lang, source })).toBe(expected)
    })

    it('keeps JavaScript highlighting for JavaScript sources', () => {
        expect(getFrameLanguage({ lang: 'javascript', source: 'src/lib/api.js' })).toBe(Language.JavaScript)
    })
})

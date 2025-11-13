import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

export type SDKLanguage = 'node' | 'python'

export function useLanguageSelector(
    defaultLanguage: SDKLanguage = 'node'
): [SDKLanguage, React.Dispatch<React.SetStateAction<SDKLanguage>>] {
    return useState<SDKLanguage>(defaultLanguage)
}

interface LanguageSelectorProps {
    language: SDKLanguage
    onChange: (language: SDKLanguage) => void
}

export function LanguageSelector({ language, onChange }: LanguageSelectorProps): JSX.Element {
    return (
        <>
            <h3>Choose your language</h3>
            <LemonTabs
                activeKey={language}
                onChange={(key) => onChange(key as SDKLanguage)}
                tabs={[
                    { key: 'node', label: 'Node.js' },
                    { key: 'python', label: 'Python' },
                ]}
            />
        </>
    )
}
